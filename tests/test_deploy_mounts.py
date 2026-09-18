"""
钉住 docker-compose.yml 的挂载约束：**只挂目录，不挂单文件。**

为什么这条约束值一个测试：docker 把单个文件 bind mount 进容器时，那个文件是
一个挂载点，而 Linux 的 rename(2) 拒绝把别的文件改名覆盖到挂载点上，返回 EBUSY。
`accounts.enc` 走的正是 `.tmp` + `os.replace` 原子写，所以在「单文件挂载」的
compose 下，**每一次保存账号/配置都会 500**，而本地直接跑 python 却完全正常 ——
这类只在部署形态下才现形的 bug，单测代码逻辑是测不出来的，只能钉住部署约束本身。

只用标准库解析：tests/ 不引入新依赖（YAML 库不是本项目的依赖）。
"""

import unittest
from pathlib import Path

from backend import paths

COMPOSE_PATH = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def parse_bind_mounts(text: str) -> list[tuple[str, str, str]]:
    """从 compose 文本里取出 bind mount，返回 [(source, target, options)]。

    只认 `volumes:` 块下、源为绝对路径（以 / 开头）的条目；具名卷与匿名卷跳过
    （它们由 docker 管理，不涉及宿主机单文件）。
    """
    mounts: list[tuple[str, str, str]] = []
    volumes_indent: int | None = None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if stripped == "volumes:":
            volumes_indent = indent
            continue

        if volumes_indent is None:
            continue

        # 缩进退回同级或更浅，说明 volumes 块结束了
        if indent <= volumes_indent:
            volumes_indent = None
            continue

        if not stripped.startswith("- "):
            continue

        spec = stripped[2:].strip().strip('"').strip("'")
        if not spec.startswith("/"):
            continue

        parts = spec.split(":")
        if len(parts) >= 2:
            mounts.append((parts[0], parts[1], ":".join(parts[2:])))

    return mounts


class DeployMountsTestCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(COMPOSE_PATH.exists(), f"找不到 {COMPOSE_PATH}")
        self.mounts = parse_bind_mounts(COMPOSE_PATH.read_text(encoding="utf-8"))
        self.assertTrue(self.mounts, "docker-compose.yml 里没解析出任何 bind mount，解析器或文件结构变了")

    def test_no_single_file_bind_mounts(self):
        """挂载源必须是目录 —— 末段带扩展名即视为单文件。"""
        offenders = [src for src, _, _ in self.mounts if "." in Path(src).name]
        self.assertEqual(
            offenders, [],
            "docker-compose.yml 把单个文件 bind mount 进了容器："
            f"{offenders}。挂载点是 mountpoint，rename(2) 覆盖它会 EBUSY，"
            "凡是走 .tmp + os.replace 原子写的文件（accounts.enc）都会写失败。"
            "改成挂载所在目录，并用 RARICY_* 环境变量把路径指过去。",
        )

    def test_no_app_data_file_is_a_mount_target(self):
        """容器内挂载点不得正好是应用要原子替换的那些文件。"""
        data_files = {
            paths.CONFIG_PATH.name,
            paths.ACCOUNTS_ENC_PATH.name,
            paths.ACCOUNTS_PLAIN_PATH.name,
            paths.KEY_PATH.name,
        }
        offenders = [target for _, target, _ in self.mounts if Path(target).name in data_files]
        self.assertEqual(
            offenders, [],
            f"这些挂载点正好是应用的数据文件：{offenders}。"
            "它们必须位于被挂载的目录**内部**，而不是自己成为挂载点。",
        )


class ParserTestCase(unittest.TestCase):
    """解析器本身的测试 —— 一个永远返回空列表的解析器会让上面两个断言空转通过。"""

    SAMPLE = """\
services:
  checkin:
    image: x
    volumes:
      - /host/data:/app/data:Z
      - /host/key:/app/key:ro,Z
      - named_volume:/app/named
      - /host/file.json:/app/file.json:Z
    environment:
      TZ: Asia/Shanghai
    logging:
      driver: json-file
"""

    def test_extracts_only_absolute_source_bind_mounts(self):
        mounts = parse_bind_mounts(self.SAMPLE)
        sources = [src for src, _, _ in mounts]
        self.assertEqual(sources, ["/host/data", "/host/key", "/host/file.json"])

    def test_parses_target_and_options(self):
        mounts = parse_bind_mounts(self.SAMPLE)
        self.assertIn(("/host/data", "/app/data", "Z"), mounts)
        self.assertIn(("/host/key", "/app/key", "ro,Z"), mounts)

    def test_stops_at_end_of_volumes_block(self):
        """environment: 块里的 `TZ: Asia/Shanghai` 不能被当成分卷。"""
        mounts = parse_bind_mounts(self.SAMPLE)
        self.assertNotIn("Asia/Shanghai", [t for _, t, _ in mounts])

    def test_detects_a_single_file_mount(self):
        """这个测试自己要先能认出 bug —— 否则整份文件是摆设。"""
        offenders = [src for src, _, _ in parse_bind_mounts(self.SAMPLE) if "." in Path(src).name]
        self.assertEqual(offenders, ["/host/file.json"])


if __name__ == "__main__":
    unittest.main()
