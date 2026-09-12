"""
Flask API 服务 — 提供打卡系统的 HTTP 接口并托管前端页面。
"""

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .checkin import CheckinEngine, load_config, save_accounts, get_enabled_accounts
from .crypto import AccountsDecryptError
from .scheduler import CheckinScheduler, get_scheduler, read_logs, get_today_status, get_today_status_all
from .blog import BlogEngine
from . import store, progress

# ── 日志配置 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")

# ── 路径 ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR.parent / "runtime"
CONFIG_PATH = BASE_DIR / "config.json"
FRONTEND_DIR = BASE_DIR.parent / "frontend"

# ── 打卡进度存储（内存）───────────────────────────────────
# 结构: { task_id: { status, steps, results, ... } }
# 超过 200 条自动清理最旧条目
_checkin_progress: dict = {}
_progress_lock = threading.Lock()


def _store_progress(task_id: str, data: dict):
    with _progress_lock:
        _checkin_progress[task_id] = data
        # 清理超过 200 条
        if len(_checkin_progress) > 200:
            oldest = sorted(_checkin_progress.keys())[:50]
            for k in oldest:
                del _checkin_progress[k]


# ── Flask 应用 ────────────────────────────────────────────
app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")


@app.errorhandler(AccountsDecryptError)
def _handle_accounts_decrypt_error(e):
    """账号密文读不出来时，宁可整个接口报错，也不能让任何路径把它当成「没有账号」。"""
    return jsonify({
        "error": "accounts_decrypt_failed",
        "message": str(e),
        "hint": "请确认 runtime/.accounts.key 与 backend/accounts.enc 是配套的同一套。"
                "账号不会被自动覆盖，修好之前请勿在配置面板保存。",
    }), 500


# ── 配置读写工具 ──────────────────────────────────────────
def save_config(data: dict):
    """保存配置到文件（accounts 单独加密保存到 accounts.enc，不写入 config.json）"""
    accounts = data.pop("accounts", None)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if accounts is not None:
        save_accounts(accounts)


def mask_sensitive(config: dict) -> dict:
    """脱敏：隐藏密码字段"""
    masked = json.loads(json.dumps(config))
    if "accounts" in masked:
        for acc in masked["accounts"]:
            if acc.get("password"):
                acc["password"] = "****"
    return masked


# ── 路由：前端页面 ────────────────────────────────────────
@app.route("/")
def index():
    """返回前端控制面板"""
    return send_from_directory(str(FRONTEND_DIR), "index.html")


# ── 路由：健康检查 ────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "checkin-system"})


# ── 路由：打卡状态 ────────────────────────────────────────
@app.route("/api/status")
def status():
    """返回今日打卡状态和下次定时信息"""
    today_status = get_today_status_all()
    scheduler = get_scheduler()
    next_run = scheduler.get_next_run()

    config = load_config()
    schedule_enabled = config.get("schedule", {}).get("enabled", True)
    schedule_times = config.get("schedule", {}).get("times", [])

    # 汇总：任一账号已打卡即表示今日已打卡
    any_checked = any(v is not None for v in today_status.values())

    return jsonify({
        "today_checked": any_checked,
        "today_record": list(today_status.values())[0] if today_status else None,
        "account_status": today_status,  # {username: record_or_None}
        "next_scheduled": next_run,
        "schedule_enabled": schedule_enabled,
        "schedule_times": schedule_times,
    })


# ── 路由：手动打卡（异步 + 进度追踪）─────────────────────
@app.route("/api/checkin", methods=["POST"])
def trigger_checkin():
    """
    手动触发打卡（异步执行，返回 task_id 用于轮询进度）。

    Body（可选）:
        { "accounts": ["user1", "user2"] }   → 仅为指定账号打卡
        { "accounts": ["all"] }              → 为所有启用账号打卡
        {}                                    → 默认为所有启用账号
    """
    body = request.get_json(silent=True) or {}
    account_usernames = body.get("accounts", ["all"])
    task_id = str(uuid.uuid4())[:8]

    # 初始化进度
    _store_progress(task_id, {
        "task_id": task_id,
        "status": "pending",
        "current_step": "",
        "current_account": "",
        "account_index": 0,
        "total_accounts": 0,
        "results": [],
        "steps": [],
        "done": False,
    })

    logger.info("🖐 手动打卡触发 [%s]，账号: %s", task_id, account_usernames)

    def _run():
        scheduler = get_scheduler()

        def progress_cb(step: str, message: str):
            """进度回调：更新存储"""
            data = _checkin_progress.get(task_id, {})
            data["current_step"] = step
            data["current_message"] = message
            data["steps"].append({"step": step, "message": message,
                                  "time": datetime.now().strftime("%H:%M:%S")})
            _store_progress(task_id, data)

        # 获取目标账号
        from .checkin import get_enabled_accounts
        accounts = get_enabled_accounts()
        if account_usernames and "all" not in account_usernames:
            target_accounts = [a for a in accounts if a["username"] in account_usernames]
        else:
            target_accounts = accounts

        _store_progress(task_id, {**_checkin_progress.get(task_id, {}),
                                   "total_accounts": len(target_accounts)})

        all_results = []
        for i, account in enumerate(target_accounts):
            username = account["username"]
            password = account.get("password", "")

            # 更新当前账号进度
            _store_progress(task_id, {
                **_checkin_progress.get(task_id, {}),
                "current_account": username,
                "account_index": i + 1,
                "current_step": "login",
                "current_message": f"正在为 {username} 登录...",
            })

            from .checkin import CheckinEngine
            engine = CheckinEngine()

            try:
                result = engine.execute(username, password, progress_callback=progress_cb)
                result["account"] = username
            except Exception as e:
                result = {
                    "success": False,
                    "message": str(e),
                    "account": username,
                    "already_checked": False,
                    "fortune": None,
                    "steps": [],
                }
            finally:
                engine.quit()

            all_results.append(result)

            # 记录日志（复用 scheduler 的日志函数）
            from .scheduler import write_log
            now = datetime.now()
            log_entry = {
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "account": username,
                "success": result["success"],
                "message": result["message"],
                "already_checked": result.get("already_checked", False),
                "fortune": result.get("fortune"),
                "duration_seconds": result.get("duration_seconds", 0),
                "trigger": "manual",
            }
            write_log(log_entry)

            # 切换账号时清除 session
            if i < len(target_accounts) - 1:
                engine.clear_session()

        # 完成
        all_success = all(r["success"] for r in all_results)
        _store_progress(task_id, {
            **_checkin_progress.get(task_id, {}),
            "status": "done",
            "current_step": "done",
            "current_message": "全部完成",
            "done": True,
            "results": all_results,
            "total": len(all_results),
            "success_count": sum(1 for r in all_results if r["success"]),
            "all_success": all_success,
        })

        icon = "✅" if all_success else "❌"
        logger.info("%s [%s] 手动打卡完成: %d/%d 成功",
                     icon, task_id,
                     sum(1 for r in all_results if r["success"]), len(all_results))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"task_id": task_id}), 202


@app.route("/api/checkin/progress/<task_id>")
def checkin_progress(task_id):
    """轮询打卡进度"""
    progress = _checkin_progress.get(task_id)
    if progress is None:
        return jsonify({"error": "任务不存在或已过期"}), 404
    return jsonify(progress)


# ── 路由：打卡面板 ────────────────────────────────────────
@app.route("/checkin")
def checkin_index():
    """返回打卡控制面板"""
    return send_from_directory(str(FRONTEND_DIR), "checkin.html")


# ── 路由：配置面板 ────────────────────────────────────────
@app.route("/config")
def config_index():
    """返回配置面板"""
    return send_from_directory(str(FRONTEND_DIR), "config.html")


# ── 路由：博客管理 ────────────────────────────────────────
@app.route("/blog")
def blog_index():
    """返回博客控制面板"""
    return send_from_directory(str(FRONTEND_DIR), "blog.html")


@app.route("/api/blog/articles")
def blog_articles():
    """分页 + 服务端筛选 + 排序的文章列表"""
    args = request.args
    author = args.get("author", "").strip() or None
    category = args.get("category", "").strip() or None
    min_likes = args.get("min_likes", type=int)
    status = args.get("status", "").strip() or None
    if status not in (None, "fetched", "unfetched"):
        status = None
    sort = args.get("sort", "").strip() or None
    order = args.get("order", "asc").strip().lower()
    if order not in ("asc", "desc"):
        order = "asc"
    page = max(1, args.get("page", 1, type=int))
    page_size = min(200, max(1, args.get("page_size", 50, type=int)))

    offset = (page - 1) * page_size
    rows, total = store.query_articles(
        author=author, category=category, min_likes=min_likes, status=status,
        sort=sort, order=order, offset=offset, limit=page_size,
    )
    likes = store.get_likes_for_articles([r["id"] for r in rows])
    has_more = offset + len(rows) < total
    return jsonify({
        "articles": rows, "likes": likes, "total": total,
        "page": page, "page_size": page_size, "has_more": has_more,
    })


@app.route("/api/blog/articles/all")
def blog_articles_all():
    """加载全部文章（同一筛选/排序，无分页；约 1 万条上限）"""
    args = request.args
    author = args.get("author", "").strip() or None
    category = args.get("category", "").strip() or None
    min_likes = args.get("min_likes", type=int)
    status = args.get("status", "").strip() or None
    if status not in (None, "fetched", "unfetched"):
        status = None
    sort = args.get("sort", "").strip() or None
    order = args.get("order", "asc").strip().lower()
    if order not in ("asc", "desc"):
        order = "asc"
    rows, total = store.query_articles(
        author=author, category=category, min_likes=min_likes, status=status,
        sort=sort, order=order, offset=0, limit=10000,
    )
    likes = store.get_likes_for_articles([r["id"] for r in rows])
    return jsonify({"articles": rows, "likes": likes, "total": total})


@app.route("/api/blog/clear", methods=["POST"])
def blog_clear():
    """清空文章与点赞记录"""
    store.clear_all()
    return jsonify({"ok": True})


@app.route("/api/blog/meta")
def blog_meta():
    """作者/分类下拉选项"""
    return jsonify({
        "authors": store.list_distinct_authors(),
        "categories": store.list_distinct_categories(),
    })


@app.route("/api/blog/like-stats")
def blog_like_stats():
    """各账号今日点赞额度统计（已用/可用，每日上限由 DAILY_LIKE_LIMIT 决定）。"""
    from .blog import DAILY_LIKE_LIMIT
    accounts = get_enabled_accounts()
    result = {}
    for acc in accounts:
        username = acc["username"]
        used = store.count_today_likes(username)
        result[username] = {"used": used, "available": max(0, DAILY_LIKE_LIMIT - used)}
    return jsonify({"limit": DAILY_LIKE_LIMIT, "accounts": result})


@app.route("/api/blog/article/<article_id>")
def blog_article_detail(article_id):
    """单篇详情（含 content，供查看弹窗）"""
    rows = store.get_articles_by_ids([article_id])
    if not rows:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(rows[0])


@app.route("/api/blog/scan", methods=["POST"])
def blog_scan():
    """异步扫描博客目录（使用第一个启用账号的已认证 session）"""
    task_id = progress.new_task()
    progress.store_progress(task_id, {"status": "pending", "steps": [], "results": {}, "done": False})

    def _run():
        progress.watchdog(task_id, 900)  # 15 分钟看门狗，防止线程挂死
        def cb(step, msg, done=None, total=None):
            data = progress.get_progress(task_id) or {}
            data["current_step"] = step
            data["steps"].append({"step": step, "message": msg, "time": datetime.now().strftime("%H:%M:%S")})
            if done is not None:
                data["done_count"] = done
            if total is not None:
                data["total_count"] = total
            progress.store_progress(task_id, data)

        engine = None
        try:
            engine = BlogEngine()
            # 扫描需要已认证 session 才能拿到完整列表
            accounts = get_enabled_accounts()
            if not accounts:
                progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": "没有启用的账号"}})
                return
            engine.login(accounts[0]["username"], accounts[0]["password"])
            results = engine.scan_directory(progress_cb=cb)
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": results})
        except Exception as e:
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": str(e)}})
        finally:
            if engine is not None:
                engine.clear_session()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id}), 202


@app.route("/api/blog/fetch", methods=["POST"])
def blog_fetch():
    """异步抓取指定文章内容（使用第一个启用账号的已认证 session）"""
    body = request.get_json(silent=True) or {}
    article_ids = body.get("article_ids", [])
    task_id = progress.new_task()
    progress.store_progress(task_id, {"status": "pending", "steps": [], "results": {}, "done": False})

    def _run():
        progress.watchdog(task_id, 900)  # 15 分钟看门狗，防止线程挂死
        def cb(step, msg, done=None, total=None):
            data = progress.get_progress(task_id) or {}
            data["current_step"] = step
            data["steps"].append({"step": step, "message": msg, "time": datetime.now().strftime("%H:%M:%S")})
            if done is not None:
                data["done_count"] = done
            if total is not None:
                data["total_count"] = total
            progress.store_progress(task_id, data)

        engine = None
        try:
            engine = BlogEngine()
            accounts = get_enabled_accounts()
            if not accounts:
                progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": "没有启用的账号"}})
                return
            engine.login(accounts[0]["username"], accounts[0]["password"])
            results = engine.fetch_contents(article_ids, progress_cb=cb)
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": results})
        except Exception as e:
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": str(e)}})
        finally:
            if engine is not None:
                engine.clear_session()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id}), 202


@app.route("/api/blog/like", methods=["POST"])
def blog_like():
    """异步批量点赞指定文章（使用请求中指定的账号）"""
    body = request.get_json(silent=True) or {}
    article_ids = body.get("article_ids", [])
    account = body.get("account", "")
    task_id = progress.new_task()
    progress.store_progress(task_id, {"status": "pending", "steps": [], "results": {}, "done": False})

    def _run():
        progress.watchdog(task_id, 900)  # 15 分钟看门狗，防止线程挂死
        def cb(step, msg, done=None, total=None):
            data = progress.get_progress(task_id) or {}
            data["current_step"] = step
            data["steps"].append({"step": step, "message": msg, "time": datetime.now().strftime("%H:%M:%S")})
            if done is not None:
                data["done_count"] = done
            if total is not None:
                data["total_count"] = total
            progress.store_progress(task_id, data)

        engine = None
        try:
            engine = BlogEngine()
            accounts = get_enabled_accounts()
            target = next((a for a in accounts if a["username"] == account), None)
            if not target:
                progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": "账号不存在或未启用"}})
                return
            results = engine.like_articles(article_ids, target["username"], target["password"], progress_cb=cb)
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": results})
        except Exception as e:
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": str(e)}})
        finally:
            if engine is not None:
                engine.clear_session()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id}), 202


@app.route("/api/blog/progress/<task_id>")
def blog_progress(task_id):
    """轮询博客任务进度"""
    p = progress.get_progress(task_id)
    if p is None:
        return jsonify({"error": "任务不存在或已过期"}), 404
    return jsonify(p)


# ── 路由：打卡日志 ────────────────────────────────────────
@app.route("/api/logs")
def logs():
    """返回打卡历史记录"""
    limit = request.args.get("limit", 30, type=int)
    limit = min(limit, 200)  # 最多 200 条
    return jsonify(read_logs(limit=limit))


# ── 路由：账号管理 ────────────────────────────────────────
@app.route("/api/accounts", methods=["GET"])
def get_accounts():
    """获取所有账号列表（密码脱敏）"""
    config = load_config()
    accounts = config.get("accounts", [])
    # 兼容旧配置
    if not accounts:
        site = config.get("site", {})
        username = site.get("username", "")
        if username:
            accounts = [{
                "username": username,
                "password": "****",
                "enabled": True,
            }]
    masked = []
    for acc in accounts:
        m = dict(acc)
        if m.get("password"):
            m["password"] = "****"
        masked.append(m)
    return jsonify(masked)


@app.route("/api/accounts", methods=["POST"])
def update_accounts():
    """
    更新账号列表。
    Body: 完整的 accounts 数组 [{username, password, enabled}, ...]
    密码为 "****" 的项保留原密码。
    """
    body = request.get_json()
    if body is None or not isinstance(body, list):
        return jsonify({"error": "请求体必须为账号数组"}), 400

    config = load_config()
    old_accounts = config.get("accounts", [])
    old_map = {a["username"]: a.get("password", "") for a in old_accounts}

    # 合并密码：如果传入 "****" 则保留原密码
    for acc in body:
        if acc.get("password") == "****":
            acc["password"] = old_map.get(acc["username"], "")

    config["accounts"] = body
    save_config(config)

    # 重启调度器以应用新账号
    scheduler = get_scheduler()
    scheduler.restart()

    logger.info("账号列表已更新，共 %d 个账号", len(body))
    return jsonify({"ok": True, "message": f"已保存 {len(body)} 个账号", "count": len(body)})


# ── 路由：配置读取 ────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
def get_config():
    """获取当前配置（密码脱敏）"""
    config = load_config()
    return jsonify(mask_sensitive(config))


# ── 路由：配置更新 ────────────────────────────────────────
@app.route("/api/config", methods=["POST"])
def update_config():
    """
    更新配置。
    Body: { "path": ["site", "username"], "value": "new_value" }
    或完整配置对象（替换整个 config）
    """
    body = request.get_json()
    if body is None:
        return jsonify({"error": "请求体不能为空"}), 400

    config = load_config()
    path = body.get("path")
    value = body.get("value")

    if path and isinstance(path, list):
        # 按路径更新单个字段
        node = config
        for key in path[:-1]:
            if key not in node:
                node[key] = {}
            node = node[key]

        # 密码字段特殊处理：如果传入 **** 则保留原密码
        if path[-1] == "password" and value == "****":
            pass  # 不修改密码
        else:
            node[path[-1]] = value

        save_config(config)
        logger.info("配置已更新: %s = %s", ".".join(path),
                     "****" if path[-1] == "password" else value)

    elif isinstance(body, dict) and "path" not in body:
        # 传入完整配置对象 → 合并更新
        incoming = body
        # 如果密码为 ****，保留原密码（accounts 级别）
        old_accounts = config.get("accounts", [])
        old_pwd_map = {a["username"]: a.get("password", "") for a in old_accounts}
        for acc in incoming.get("accounts", []):
            if acc.get("password") == "****":
                acc["password"] = old_pwd_map.get(acc["username"], "")
        config = incoming
        save_config(config)
        logger.info("配置已整体更新")
    else:
        return jsonify({"error": "请提供 path + value 或完整配置对象"}), 400

    # 配置变更后重启调度器
    scheduler = get_scheduler()
    scheduler.restart()

    return jsonify({"ok": True, "message": "配置已保存，调度器已重启"})


def create_app():
    """创建并初始化 Flask 应用（工厂函数）"""
    # 确保必要目录存在（runtime 必须先于 blog 数据库初始化）
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    (RUNTIME_DIR / "logs").mkdir(parents=True, exist_ok=True)
    store.init_db()

    # 启动调度器
    scheduler = get_scheduler()
    scheduler.start()

    return app


if __name__ == "__main__":
    create_app()
    app.run(host="127.0.0.1", port=5000, debug=False)
