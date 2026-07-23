"""
定时调度器 — 基于 APScheduler 管理打卡定时任务。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

from .checkin import CheckinEngine, load_config, get_enabled_accounts

# ── 路径 ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR.parent / "runtime"
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = RUNTIME_DIR / "logs" / "checkin_log.json"

logger = logging.getLogger(__name__)


# ── 日志管理 ──────────────────────────────────────────────
def read_logs(limit: int = 30) -> list:
    """读取打卡日志，最新在前"""
    if not LOG_PATH.exists():
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return data[:limit]
    except (json.JSONDecodeError, OSError):
        return []


def write_log(entry: dict):
    """追加一条打卡日志"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except (json.JSONDecodeError, OSError):
            logs = []
    logs.append(entry)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def get_today_status() -> Optional[dict]:
    """获取今日打卡状态，返回最新的今日记录或 None（兼容旧接口）"""
    logs = read_logs(limit=500)
    today = datetime.now().strftime("%Y-%m-%d")
    for entry in logs:
        if entry.get("date") == today:
            return entry
    return None


def get_today_status_all() -> dict[str, Optional[dict]]:
    """获取所有账号的今日打卡状态，返回 {username: record_or_None}"""
    logs = read_logs(limit=500)
    today = datetime.now().strftime("%Y-%m-%d")
    accounts = get_enabled_accounts()
    result = {}
    for acc in accounts:
        username = acc["username"]
        # 找到该账号今日的最新记录
        for entry in logs:
            if entry.get("date") == today and entry.get("account") == username:
                result[username] = entry
                break
        else:
            result[username] = None
    return result


# ── 调度器封装 ────────────────────────────────────────────
class CheckinScheduler:
    """打卡定时调度器"""

    def __init__(self):
        self._scheduler: Optional[BackgroundScheduler] = None
        self._engine: Optional[CheckinEngine] = None

    @property
    def scheduler(self) -> BackgroundScheduler:
        if self._scheduler is None:
            self._scheduler = BackgroundScheduler(
                timezone="Asia/Shanghai",
                job_defaults={"misfire_grace_time": 300, "coalesce": True},
            )
        return self._scheduler

    @property
    def engine(self) -> CheckinEngine:
        if self._engine is None:
            self._engine = CheckinEngine()
        return self._engine

    # ── 打卡任务回调 ──────────────────────────────────

    def _checkin_job(self):
        """定时任务回调：为所有启用账号执行打卡并记录日志"""
        config = load_config()
        times_str = ", ".join(config["schedule"].get("times", []))

        accounts = get_enabled_accounts()
        if not accounts:
            logger.warning("⚠ 没有启用的账号，跳过定时打卡")
            return

        logger.info("⏰ 定时打卡触发 [%s]，共 %d 个账号", datetime.now(), len(accounts))

        all_results = []
        for i, account in enumerate(accounts):
            username = account["username"]
            password = account.get("password", "")

            # 切换账号时清除上一账号的 cookies，强制重新登录
            if i > 0:
                self.engine.clear_session()

            logger.info("  → 正在为账号 %s 打卡...", username)
            result = self.engine.execute(username, password)
            result["account"] = username

            # 写入日志
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
                "trigger": "scheduled",
            }
            write_log(log_entry)

            # 运势结果日志
            if result.get("fortune") and result["fortune"].get("handled"):
                f = result["fortune"]
                logger.info("🔮 [%s] 运势卡片: 第%d/%d张, 结果: %s",
                             username,
                             f.get("card_selected", -1) + 1,
                             f.get("total_cards", 0),
                             f.get("result_text", ""))

            status_icon = "✅" if result["success"] else "❌"
            logger.info("%s [%s] 定时打卡结果: %s", status_icon, username, result["message"])
            all_results.append(result)

        # 打卡完所有账号后退出浏览器
        self.engine.quit()

        return all_results

    def manual_checkin(self, account_usernames: list[str] | None = None) -> list[dict]:
        """
        手动触发打卡（通过 API 调用）。

        Args:
            account_usernames: 要打卡的账号用户名列表。
                               None 或 ["all"] → 所有启用账号。
                               ["user1", "user2"] → 仅指定账号。
        """
        accounts = get_enabled_accounts()

        # 筛选目标账号
        if account_usernames and "all" not in account_usernames:
            target_accounts = [
                a for a in accounts if a["username"] in account_usernames
            ]
        else:
            target_accounts = accounts

        if not target_accounts:
            return [{"success": False, "message": "没有匹配的启用账号", "account": ""}]

        all_results = []
        for i, account in enumerate(target_accounts):
            username = account["username"]
            password = account.get("password", "")

            # 切换账号时清除上一账号的 cookies，强制重新登录
            if i > 0:
                self.engine.clear_session()

            result = self.engine.execute(username, password)
            result["account"] = username

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

            # 运势结果日志
            if result.get("fortune") and result["fortune"].get("handled"):
                f = result["fortune"]
                logger.info("🔮 [%s] 运势卡片: 第%d/%d张, 结果: %s",
                             username,
                             f.get("card_selected", -1) + 1,
                             f.get("total_cards", 0),
                             f.get("result_text", ""))

            all_results.append(result)

        # 打卡完所有账号后退出浏览器
        self.engine.quit()

        return all_results

    # ── 调度器生命周期 ────────────────────────────────

    def start(self):
        """启动调度器：读取配置，创建所有定时任务"""
        config = load_config()
        schedule_cfg = config.get("schedule", {})
        enabled = schedule_cfg.get("enabled", True)
        times = schedule_cfg.get("times", [])
        timezone = schedule_cfg.get("timezone", "Asia/Shanghai")

        # 更新时区
        if self._scheduler:
            self._scheduler.configure(timezone=timezone)

        # 移除旧任务
        self._remove_all_jobs()

        if not enabled:
            logger.info("⏸ 定时调度已禁用")
            return

        if not times:
            logger.warning("⚠ 未配置打卡时间，调度器空闲")
            return

        # 为每个时间点创建 CronTrigger
        for t in times:
            try:
                hour, minute = map(int, t.split(":"))
                job_id = f"checkin_{hour:02d}{minute:02d}"
                trigger = CronTrigger(
                    hour=hour,
                    minute=minute,
                    timezone=timezone,
                )
                self.scheduler.add_job(
                    self._checkin_job,
                    trigger=trigger,
                    id=job_id,
                    name=f"打卡 {t}",
                    replace_existing=True,
                )
                logger.info("📅 已添加定时任务: 每天 %s", t)
            except ValueError:
                logger.error("❌ 时间格式错误: %s", t)

        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("🚀 调度器已启动")

    def _remove_all_jobs(self):
        """移除所有打卡定时任务"""
        if self._scheduler is None:
            return
        for job in self._scheduler.get_jobs():
            if job.id.startswith("checkin_"):
                try:
                    self._scheduler.remove_job(job.id)
                except JobLookupError:
                    pass

    def shutdown(self):
        """关闭调度器"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("🛑 调度器已关闭")

    def restart(self):
        """重启调度器（配置变更后调用）"""
        self.shutdown()
        self._scheduler = None
        self.start()

    def get_next_run(self) -> Optional[str]:
        """获取下一次打卡时间"""
        if self._scheduler is None:
            return None
        jobs = [j for j in self._scheduler.get_jobs() if j.id.startswith("checkin_")]
        if not jobs:
            return None
        next_times = [j.next_run_time for j in jobs if j.next_run_time]
        if not next_times:
            return None
        earliest = min(next_times)
        return earliest.strftime("%Y-%m-%d %H:%M:%S")


# ── 全局单例 ──────────────────────────────────────────────
_instance: Optional[CheckinScheduler] = None


def get_scheduler() -> CheckinScheduler:
    """获取调度器全局单例"""
    global _instance
    if _instance is None:
        _instance = CheckinScheduler()
    return _instance
