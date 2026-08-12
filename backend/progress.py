# backend/progress.py
"""
通用任务进度存储（内存）— 打卡与 blog 模块共享。
结构: { task_id: { status, steps, results, ... } }
线程安全（Lock 保护），超过 200 条自动清理最旧条目。
"""
import threading
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
