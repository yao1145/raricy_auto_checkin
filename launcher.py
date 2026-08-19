"""
一键打卡启动器 — 双击桌面快捷方式后执行。

行为：
  1. 检测本机是否已有打卡服务在运行。
     自动发现端口：先查默认 5000，再通过 run.py 进程 + netstat 找出其实际监听端口。
  2. 已运行 → 直接打开浏览器控制面板（使用该服务实际端口），退出。
  3. 未运行 → 前台启动 run.py（窗口保留日志，Ctrl+C 停止），run.py 会自动打开浏览器。

调试：设置环境变量 LAUNCHER_NO_BROWSER=1 可禁止自动打开浏览器。
"""

import base64
import json
import os
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 5000
NO_BROWSER = os.environ.get("LAUNCHER_NO_BROWSER") == "1"


def _health_ok(url: str) -> bool:
    """健康检查：确认该 URL 返回的是本系统服务（service == checkin-system）。"""
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=2) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("ok") is True and data.get("service") == "checkin-system"
    except Exception:
        return False


def _run_pids() -> set[int]:
    """返回命令行包含 run.py 的 python 进程 PID（即可能正在运行的服务进程）。"""
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^python(w)?\\.exe$' -and $_.CommandLine -like '*run.py*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return set()
    return {int(line.strip()) for line in out.splitlines() if line.strip().isdigit()}


def _pids_listening_ports(pids: set[int]) -> set[int]:
    """返回这些 PID 正在 LISTENING 的本地 TCP 端口。"""
    if not pids:
        return set()
    pid_set = {str(p) for p in pids}
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return set()
    ports = set()
    for line in out.splitlines():
        parts = line.split()
        # 形如: TCP  127.0.0.1:5000  0.0.0.0:0  LISTENING  12345
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" and parts[4] in pid_set:
            local = parts[1]
            port = local.rsplit(":", 1)[-1]
            if port.isdigit():
                ports.add(int(port))
    return ports


def find_running_server() -> str | None:
    """返回正在运行的服务面板 URL；找不到返回 None。"""
    # 常见情况：默认端口 5000
    default_url = f"http://127.0.0.1:{DEFAULT_PORT}"
    if _health_ok(default_url):
        return default_url

    # 其他端口：找出正在运行的 run.py 进程实际监听的端口
    for port in sorted(_pids_listening_ports(_run_pids())):
        if port == DEFAULT_PORT:
            continue
        url = f"http://127.0.0.1:{port}"
        if _health_ok(url):
            return url
    return None


def main() -> int:
    panel_url = find_running_server()
    if panel_url is not None:
        print(f"[OK] 服务已在运行（{panel_url}），打开控制面板...")
        if not NO_BROWSER:
            webbrowser.open(panel_url)
        return 0

    print("[启动] 服务未运行，正在启动 Flask 服务...")
    print("      服务启动后会自动打开浏览器控制面板。")
    print("      按 Ctrl+C 可停止服务。")

    cmd = [sys.executable, "run.py"]
    if NO_BROWSER:
        cmd.append("--no-browser")

    try:
        code = subprocess.run(cmd, cwd=str(BASE_DIR)).returncode
    except KeyboardInterrupt:
        print("\n[停止] 服务已停止。")
        return 0

    if code != 0:
        print("[错误] 启动失败，请检查上方日志。")
        print("       若提示端口被占用，可能服务已在运行或上次未正常退出。")
        input("按回车键关闭窗口...")
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
