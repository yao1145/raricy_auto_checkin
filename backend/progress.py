# backend/progress.py
"""
通用任务进度存储（内存）— 打卡与 blog 模块共享。
结构: { task_id: { status, steps, results, ... } }
线程安全（Lock 保护），超过 200 条自动清理最旧条目。
"""
import threading
import time
import uuid

_checkin_progress: dict = {}
_lock = threading.Lock()


def new_task() -> str:
    return str(uuid.uuid4())[:8]


def store_progress(task_id: str, data: dict) -> None:
    with _lock:
        _checkin_progress[task_id] = data
        if len(_checkin_progress) > 200:
            oldest = sorted(_checkin_progress.keys())[:50]
            for k in oldest:
                del _checkin_progress[k]


def get_progress(task_id: str) -> dict | None:
    with _lock:
        return _checkin_progress.get(task_id)


def watchdog(task_id: str, seconds: int) -> None:
    """看门狗：若任务在 seconds 秒后仍未完成，强制标记为超时失败。
    仅在任务尚未 done 时生效，正常完成的任务不会被覆盖。"""
    def _run():
        time.sleep(seconds)
        with _lock:
            data = _checkin_progress.get(task_id)
            if data and not data.get("done"):
                data = dict(data)
                data["status"] = "done"
                data["done"] = True
                data["results"] = {"error": "任务超时"}
                _checkin_progress[task_id] = data

    t = threading.Thread(target=_run, daemon=True)
    t.start()
