# backend/accounts_tool.py
"""
账号文件迁移与检查 CLI。

    python -m backend.accounts_tool status    # 看现状，不动文件
    python -m backend.accounts_tool encrypt   # 明文 → 密文

迁移刻意做成显式命令而非启动时自动执行：一来让人清楚自己改了什么，
二来避免密钥文件误删后代码把明文又写回去。
"""

import argparse
import json
import sys

from .checkin import save_accounts
from .crypto import AccountsDecryptError, decrypt_bytes, load_or_create_key
from .paths import ACCOUNTS_ENC_PATH, ACCOUNTS_PLAIN_PATH, CONFIG_PATH, KEY_PATH

LEGACY_HINT = (
    "config.json 的 site.username / site.password 或内嵌 accounts 数组仍有明文密码，"
    "这几处不参与加密，请手动清空。"
)


def _read_plain_accounts() -> list:
    """按与 load_accounts() 相同的优先级读明文来源。"""
    if ACCOUNTS_PLAIN_PATH.exists():
        with open(ACCOUNTS_PLAIN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    if config.get("accounts"):
        return config["accounts"]
    legacy = config.get("site", {})
    if legacy.get("username"):
        return [{"username": legacy["username"],
                 "password": legacy.get("password", ""),
                 "enabled": True}]
    return []


def cmd_status() -> int:
    print(f"密钥文件    : {KEY_PATH}  {'存在' if KEY_PATH.exists() else '不存在（首次保存时自动生成）'}")
    print(f"密文文件    : {ACCOUNTS_ENC_PATH}  {'存在' if ACCOUNTS_ENC_PATH.exists() else '不存在'}")
    print(f"明文文件    : {ACCOUNTS_PLAIN_PATH}  {'存在（建议迁移后删除）' if ACCOUNTS_PLAIN_PATH.exists() else '不存在'}")

    if ACCOUNTS_ENC_PATH.exists():
        try:
            accounts = json.loads(decrypt_bytes(ACCOUNTS_ENC_PATH.read_bytes(), load_or_create_key()).decode("utf-8"))
            print(f"密文可解密  : 是，共 {len(accounts)} 个账号")
        except AccountsDecryptError as e:
            print(f"密文可解密  : 否 —— {e}")
            print("              （密钥与密文不配套。若密钥已丢失，密文无法恢复，只能重新录入账号。）")

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        if config.get("accounts") or config.get("site", {}).get("password"):
            print(f"警告        : {LEGACY_HINT}")
    except (OSError, json.JSONDecodeError):
        print(f"警告        : 无法读取 {CONFIG_PATH}")

    return 0


def cmd_encrypt(force: bool) -> int:
    accounts = _read_plain_accounts()
    if not accounts:
        print("没有找到可迁移的账号（明文文件与 config.json 都是空的）。")
        return 1

    if ACCOUNTS_ENC_PATH.exists() and not force:
        print(f"{ACCOUNTS_ENC_PATH} 已存在，未做任何改动。确认要覆盖请加 --force。")
        return 1

    save_accounts(accounts)

    # 写完立刻回读校验：解密失败或数量对不上就说明这次迁移不可信
    try:
        back = json.loads(decrypt_bytes(ACCOUNTS_ENC_PATH.read_bytes(), load_or_create_key()).decode("utf-8"))
    except AccountsDecryptError as e:
        print(f"回读校验失败：{e}")
        return 1
    if len(back) != len(accounts):
        print(f"回读校验失败：写入 {len(accounts)} 个，读出 {len(back)} 个。")
        return 1

    print(f"已加密写入 {ACCOUNTS_ENC_PATH}，共 {len(back)} 个账号，回读校验通过。")
    print()
    print("接下来（顺序别颠倒）：")
    print(f"  1. 备份密钥 {KEY_PATH} —— 密钥丢了这 {len(back)} 个账号就恢复不了，只能重新录入")
    print(f"  2. 确认面板能正常显示账号后，手动删除明文 {ACCOUNTS_PLAIN_PATH}")
    print("  3. 若之后要在服务器上跑，密钥单独传到服务器、不要和数据目录一起备份")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.accounts_tool", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="查看密钥/密文/明文现状，不改动任何文件")
    enc = sub.add_parser("encrypt", help="把明文账号加密写入 accounts.enc")
    enc.add_argument("--force", action="store_true", help="覆盖已存在的 accounts.enc")
    args = parser.parse_args(argv)

    if args.command == "status":
        return cmd_status()
    return cmd_encrypt(args.force)


if __name__ == "__main__":
    sys.exit(main())
