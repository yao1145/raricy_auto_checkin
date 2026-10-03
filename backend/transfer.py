"""批量鱼干转账：独立会话、幂等请求和持久化流水，不重试为新交易。"""
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import requests

from .client import api_url, login
from .paths import RUNTIME_DIR
from . import progress

TRANSFER_DB_PATH = RUNTIME_DIR / "transfer.db"
_batch_lock = threading.Lock()


class TransferBusyError(Exception):
    pass


def validate_settings(settings: dict, require_schedule=False) -> dict:
    if not isinstance(settings, dict):
        raise ValueError("转账设置必须为对象")
    recipient = settings.get("recipient", "")
    if not isinstance(recipient, str) or not recipient.strip():
        raise ValueError("请输入收款用户名（精确匹配）")
    raw = settings.get("amount")
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ValueError("金额需大于 0，最多 4 位小数")
    try:
        value = Decimal(str(raw))
        if not value.is_finite() or value <= 0 or value > Decimal("900719925474.0991"):
            raise ValueError("金额超出范围")
        if value != value.quantize(Decimal("0.0001")):
            raise ValueError("金额最多 4 位小数")
    except InvalidOperation:
        raise ValueError("金额需大于 0，最多 4 位小数") from None
    accounts = settings.get("accounts", ["all"])
    if (not isinstance(accounts, list) or not accounts
            or any(not isinstance(a, str) or not a for a in accounts)
            or ("all" in accounts and accounts != ["all"])):
        raise ValueError("请选择转出账号，或使用 [all]")
    note = settings.get("note", "")
    if not isinstance(note, str) or len(note.strip()) > 30:
        raise ValueError("留言最多 30 个字")
    times = settings.get("times", [])
    if not isinstance(times, list) or any(
            not isinstance(t, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in times):
        raise ValueError("定时时间需为 HH:MM")
    if require_schedule and not times:
        raise ValueError("启用定时转账前请添加时间")
    return {**settings, "recipient": recipient.strip(), "amount": format(value.normalize(), "f"),
            "accounts": list(dict.fromkeys(accounts)), "note": note.strip(),
            "times": sorted(set(times))}


def _db():
    TRANSFER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(TRANSFER_DB_PATH, timeout=15)
    conn.execute("CREATE TABLE IF NOT EXISTS transfers (operation_key TEXT PRIMARY KEY, "
                 "timestamp TEXT NOT NULL, payload TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS batches (batch_id TEXT PRIMARY KEY, request TEXT NOT NULL, accounts TEXT NOT NULL)")
    return conn


def _record(key, result):
    with closing(_db()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO transfers VALUES (?, ?, ?)",
                     (key, datetime.now().isoformat(timespec="microseconds"),
                      json.dumps(result, ensure_ascii=False)))


def _previous(key):
    with closing(_db()) as conn, conn:
        row = conn.execute("SELECT payload FROM transfers WHERE operation_key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def read_history(limit=50):
    with closing(_db()) as conn, conn:
        rows = conn.execute("SELECT payload FROM transfers ORDER BY timestamp DESC LIMIT ?",
                            (min(200, max(1, limit)),)).fetchall()
    return [json.loads(row[0]) for row in rows]


def run_batch(config, settings, batch_id, trigger, callback=None):
    """同步执行；生产调用统一由 start_batch 持有批次锁。"""
    settings = validate_settings(settings)
    accounts = [a for a in config.get("accounts", []) if a.get("enabled", True)]
    if not accounts and config.get("site", {}).get("username"):
        accounts = [{"username": config["site"]["username"], "password": config["site"].get("password", "")}]
    if settings["accounts"] != ["all"]:
        accounts = [a for a in accounts if a["username"] in settings["accounts"]]
    if not accounts:
        raise ValueError("没有匹配的启用账号")
    # 同一批次重试沿用初次选定的账号；新增账号仅参加新的批次。
    request = {k: settings[k] for k in ("recipient", "amount", "note", "accounts")}
    with closing(_db()) as conn, conn:
        row = conn.execute("SELECT request, accounts FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if row:
            if json.loads(row[0]) != request:
                raise ValueError("该批次已使用其他转账参数，请创建新批次")
            original = json.loads(row[1])
            accounts = [a for a in accounts if a["username"] in original]
        else:
            conn.execute("INSERT INTO batches VALUES (?, ?, ?)",
                         (batch_id, json.dumps(request, ensure_ascii=False),
                          json.dumps([a["username"] for a in accounts], ensure_ascii=False)))
    if not accounts:
        raise ValueError("原批次账号均已禁用或移除")
    results = []
    seen = set()
    for account in accounts:
        username = account["username"]
        result = {"account": username, "recipient": settings["recipient"], "amount": settings["amount"],
                  "batch_id": batch_id, "trigger": trigger, "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
                  "success": False, "status": "failed", "message": ""}
        session = None
        preserve_record = False
        key = "raricy-" + hashlib.sha256(f"{batch_id}:{username}".encode()).hexdigest()[:40]
        try:
            if username == settings["recipient"]:
                result.update(status="skipped", message="收款账号自身，已跳过")
            else:
                if callback:
                    callback(results, username, len(accounts))
                session = login(config, username, account.get("password", ""))
                canonical = getattr(session, "raricy_username", "") or username
                identity = getattr(session, "raricy_user_id", "") or canonical
                key = "raricy-" + hashlib.sha256(f"{batch_id}:{identity}".encode()).hexdigest()[:40]
                if canonical == settings["recipient"] or identity in seen:
                    result.update(status="skipped", message="收款账号自身或重复账号，已跳过")
                else:
                    seen.add(identity)
                    previous = _previous(key)
                    if previous:
                        if (previous["recipient"] != result["recipient"]
                                or Decimal(previous["amount"]) != Decimal(result["amount"])
                                or previous.get("note", "") != settings["note"]):
                            preserve_record = True
                            raise ValueError("该批次已使用其他转账参数，请创建新批次")
                    if previous and previous["status"] == "success":
                        result = {**previous, "duplicated": True, "message": "该笔已成交，未重复扣款"}
                    else:
                        result.update(status="pending", message="正在转账", note=settings["note"], idempotency_key=key)
                        # 写请求意图后才发包，进程中断时仍留有单号供核对。
                        _record(key, result)
                        payload = {"to_username": settings["recipient"], "amount": settings["amount"],
                                   "note": settings["note"], "idempotency_key": key}
                        for attempt in range(2):
                            try:
                                response = session.post(api_url(config, "transfer_path", "/api/fish/market/transfer"),
                                                        json=payload, timeout=20)
                                data = response.json()
                                if not isinstance(data, dict):
                                    raise ValueError("非 JSON 对象")
                                break
                            except (requests.RequestException, ValueError):
                                if attempt == 1:
                                    data = None
                        if data is None:
                            result.update(status="unknown", message="响应未确认，请核对站点流水；重试此批次使用原幂等键")
                        elif response.status_code == 200 and data.get("code") == 200:
                            result.update(status="success", success=True, message=data.get("message", "转账成功"),
                                          transfer_id=data.get("transfer_id"), balance=data.get("balance"),
                                          duplicated=bool(data.get("duplicated")))
                        else:
                            result.update(status="failed", message=data.get("message") or f"转账失败（HTTP {response.status_code}）")
        except Exception as e:
            result.update(status="failed", message=str(e))
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
        # 跳过项不覆盖同一身份已经成交的流水。
        if result["status"] != "skipped" and not preserve_record:
            _record(key, result)
        results.append(result)
        if callback:
            callback(results, "", len(accounts))
    return results


def start_batch(config, settings, batch_id, trigger="manual"):
    settings = validate_settings(settings)
    if not _batch_lock.acquire(blocking=False):
        raise TransferBusyError("已有转账批次进行中，请等待完成")
    task_id = progress.new_task()
    progress.store_progress(task_id, {"done": False, "status": "running", "batch_id": batch_id,
                                      "results": [], "current_account": "", "total": 0})

    def update(results, username, total):
        progress.store_progress(task_id, {"done": False, "status": "running", "batch_id": batch_id,
                                          "results": list(results), "current_account": username, "total": total})

    def run():
        try:
            results = run_batch(config, settings, batch_id, trigger, update)
            progress.store_progress(task_id, {"done": True, "status": "done", "batch_id": batch_id,
                                              "results": results, "total": len(results)})
        except Exception as e:
            data = progress.get_progress(task_id) or {}
            progress.store_progress(task_id, {**data, "done": True, "status": "done", "error": str(e)})
        finally:
            _batch_lock.release()

    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        _batch_lock.release()
        raise
    return task_id
