"""
自动打卡系统 — 项目入口

启动 Flask 服务器 + APScheduler 定时调度器。
默认访问 http://127.0.0.1:5000

用法:
    python run.py                  # 默认端口 5000
    python run.py --port 8080      # 指定端口
    python run.py --debug          # 调试模式
    python run.py --no-browser     # 不自动打开浏览器
"""

import argparse
import sys
import webbrowser
from pathlib import Path

# 将项目根目录加入 Python 路径（确保 backend 包可被导入）
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from backend.app import create_app, app  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="raricy.com 自动打卡系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run.py                    默认启动（端口5000）
  python run.py --port 8080        使用 8080 端口
  python run.py --no-browser       不自动打开浏览器
  python run.py --debug            调试模式（热重载）
        """,
    )
    parser.add_argument("--port", type=int, default=5000, help="服务端口（默认: 5000）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="绑定地址（默认: 127.0.0.1）")
    parser.add_argument("--debug", action="store_true", help="开启 Flask 调试模式")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    args = parser.parse_args()

    # 创建并初始化应用
    create_app()

    url = f"http://{args.host}:{args.port}"

    # 自动打开浏览器
    if not args.no_browser:
        try:
            print(f"🌐 正在打开浏览器: {url}")
            webbrowser.open(url)
        except Exception:
            print("⚠ 无法自动打开浏览器，请手动访问面板")

    print(f"""
╔══════════════════════════════════════════════╗
║       🔔 自动打卡系统 - raricy.com           ║
╠══════════════════════════════════════════════╣
║  控制面板: {url}                  ║
║  健康检查: {url}/api/health                 ║
║  API 文档: {url}/api/status                 ║
╠══════════════════════════════════════════════╣
║  按 Ctrl+C 停止服务                         ║
╚══════════════════════════════════════════════╝
    """)

    try:
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug,
            use_reloader=False,  # 避免调度器重复启动
        )
    except KeyboardInterrupt:
        print("\n🛑 服务已停止")
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"❌ 端口 {args.port} 已被占用，请使用 --port 指定其他端口")
        else:
            print(f"❌ 启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
