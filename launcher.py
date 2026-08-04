"""
一键打卡启动器 — 双击桌面快捷方式后执行。

行为：
  1. 检测 http://127.0.0.1:5000/api/health 判断服务是否已运行。
  2. 已运行 → 直接打开浏览器控制面板，退出。
  3. 未运行 → 前台启动 run.py（窗口保留日志，Ctrl+C 停止），run.py 会自动打开浏览器。

调试：设置环境变量 LAUNCHER_NO_BROWSER=1 可禁止自动打开浏览器。
"""

import os
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PANEL_URL = "http://127.0.0.1:5000"
HEALTH_URL = PANEL_URL + "/api/health"
NO_BROWSER = os.environ.get("LAUNCHER_NO_BROWSER") == "1"


def is_running() -> bool:
    """服务是否已在本机运行（端口 5000 健康检查）。"""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> int:
    if is_running():
        print("[OK] 服务已在运行，打开控制面板...")
        if not NO_BROWSER:
            webbrowser.open(PANEL_URL)
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
