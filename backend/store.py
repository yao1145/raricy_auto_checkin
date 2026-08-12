# backend/store.py
import sqlite3
from datetime import datetime
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent.parent / "runtime"


def get_db_path() -> Path:
    return RUNTIME_DIR / "blog.db"


def _conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
              id TEXT PRIMARY KEY,
              title TEXT, author TEXT, url TEXT UNIQUE,
              category TEXT, description TEXT, likes_count INTEGER DEFAULT 0,
              content TEXT, content_fetched_at TEXT,
              created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS likes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              article_id TEXT, account TEXT,
              liked_at TEXT DEFAULT (datetime('now')),
              success INTEGER, message TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert_articles(rows: list[dict]) -> int:
    conn = _conn()
    try:
        for r in rows:
            conn.execute(
                """INSERT INTO articles (id, title, author, url, category, description, likes_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     title=excluded.title, author=excluded.author,
                     category=excluded.category, description=excluded.description,
                     likes_count=excluded.likes_count""",
                (r["id"], r["title"], r["author"], r["url"], r["category"],
                 r["description"], r["likes_count"]),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def list_articles(limit: int = 500) -> list[dict]:
    conn = _conn()
    try:
        # 注意：故意不 SELECT content —— 列表载荷保持小体积。
        # content 仅在单篇抓取/查看时按需读取（get_articles_by_ids 仍返回完整行）。
        cur = conn.execute(
            """SELECT id, title, author, url, category, description,
                      likes_count, content_fetched_at, created_at
               FROM articles ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_articles_by_ids(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    conn = _conn()
    try:
        q = ",".join("?" * len(ids))
        cur = conn.execute(f"SELECT * FROM articles WHERE id IN ({q})", ids)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_content(article_id: str, content: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE articles SET content=?, content_fetched_at=? WHERE id=?",
            (content, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), article_id),
        )
        conn.commit()
    finally:
        conn.close()


def record_like(article_id: str, account: str, success: bool, message: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO likes (article_id, account, success, message) VALUES (?, ?, ?, ?)",
            (article_id, account, 1 if success else 0, message),
        )
        conn.commit()
    finally:
        conn.close()


def list_likes(limit: int = 100) -> list[dict]:
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM likes ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
