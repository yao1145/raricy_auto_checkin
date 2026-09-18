# backend/store.py
import sqlite3
from datetime import datetime
from pathlib import Path

from .paths import BLOG_DB_PATH


def get_db_path() -> Path:
    return BLOG_DB_PATH


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


# 服务端排序白名单：键 = 前端参数，值 = SQL 列表达式（固定字符串，非用户输入）。
SORT_COLUMNS = {
    "title": "title",
    "author": "author",
    "category": "category",
    "likes_count": "local_likes",
    "content_fetched_at": "COALESCE(content_fetched_at, created_at)",
}


def query_articles(author=None, category=None, min_likes=None, status=None,
                   sort=None, order="asc", offset=0, limit=50):
    """分页查询文章（服务端筛选/排序）。status: 'fetched' | 'unfetched' | None。返回 (rows, total)。"""
    where = []
    params = []
    if author:
        where.append("author = ?")
        params.append(author)
    if category:
        where.append("category = ?")
        params.append(category)
    if min_likes is not None:
        where.append("(SELECT COUNT(*) FROM likes WHERE likes.article_id = articles.id AND likes.success = 1) >= ?")
        params.append(min_likes)
    if status == "fetched":
        where.append("content_fetched_at IS NOT NULL")
    elif status == "unfetched":
        where.append("content_fetched_at IS NULL")

    order_by = "created_at DESC"
    # content_status 是派生排序，需在 SORT_COLUMNS 白名单之外单独处理，
    # 否则会被外层 allowlist 检查拦截而静默回退到 created_at DESC。
    if sort == "content_status":
        # (content_fetched_at IS NULL) 在 SQLite 中为 1=未抓取 / 0=已抓取。
        # 升序约定为“未抓取在前、已抓取在后”，故此处方向映射与常规列相反（DESC 才能让 1 排前）。
        direction = "DESC" if order == "asc" else "ASC"
        order_by = f"(content_fetched_at IS NULL) {direction}, created_at {direction}"
    elif sort in SORT_COLUMNS:
        col = SORT_COLUMNS[sort]
        direction = "ASC" if order == "asc" else "DESC"
        order_by = f"{col} {direction}, created_at {direction}"

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    conn = _conn()
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM articles{where_sql}", params)
        total = cur.fetchone()[0]
        # 注意：故意不 SELECT content —— 列表载荷保持小体积。
        cur = conn.execute(
            f"""SELECT id, title, author, url, category, description,
                       likes_count, content_fetched_at, created_at,
                       (SELECT COUNT(*) FROM likes WHERE likes.article_id = articles.id AND likes.success = 1) AS local_likes
                FROM articles{where_sql} ORDER BY {order_by} LIMIT ? OFFSET ?""",
            params + [limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows, total
    finally:
        conn.close()


def list_distinct_authors() -> list[str]:
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT DISTINCT author FROM articles WHERE author IS NOT NULL AND author != '' ORDER BY author")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def list_distinct_categories() -> list[str]:
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT DISTINCT category FROM articles WHERE category IS NOT NULL AND category != '' ORDER BY category")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def get_likes_for_articles(article_ids: list[str]) -> list[dict]:
    if not article_ids:
        return []
    conn = _conn()
    try:
        q = ",".join("?" * len(article_ids))
        cur = conn.execute(
            f"SELECT * FROM likes WHERE article_id IN ({q}) ORDER BY id DESC", article_ids)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def has_liked(article_id: str, account: str) -> bool:
    """该账号是否已成功点赞过这篇文章"""
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT 1 FROM likes WHERE article_id=? AND account=? AND success=1 LIMIT 1",
            (article_id, account),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def count_today_likes(account: str) -> int:
    """该账号今日成功点赞次数（按本地时区计日）。"""
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM likes WHERE account=? AND success=1 "
            "AND date(liked_at, 'localtime') = date('now', 'localtime')",
            (account,),
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


def clear_all() -> None:
    """清空文章与点赞记录"""
    conn = _conn()
    try:
        conn.execute("DELETE FROM likes")
        conn.execute("DELETE FROM articles")
        conn.commit()
    finally:
        conn.close()
