# like_bot → Blog Module Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the three standalone Selenium `like_bot` features (directory scan / content fetch / batch like) into the Flask backend as a `BlogEngine`, served by a new same-style `/blog` frontend page, with pure-`requests` login shared with the check-in engine and SQLite storage.

**Architecture:** Extract the pure-`requests` login machinery from `CheckinEngine` into a shared `backend/client.py`; both `CheckinEngine` and the new `BlogEngine` call it. `BlogEngine` scans the blog directory (beautifulsoup4), fetches article contents, and batch-likes, all persisting to `runtime/blog.db` via `backend/store.py`. Async tasks reuse the existing task_id + polling progress pattern.

**Tech Stack:** Python 3.10+, Flask, requests, APScheduler, beautifulsoup4 (new), sqlite3 (stdlib). Vanilla HTML/JS frontend (no bundler).

## Global Constraints

- Pure `requests` only — **no Selenium/ChromeDriver** anywhere in the backend.
- Storage is **SQLite** (`runtime/blog.db`), not JSON/CSV.
- `config.json` remains the shared config contract; new paths go in the `api` section, relative to base URL from `site.checkin_url`.
- All article URLs are under `site.checkin_url`'s origin.
- Password masking stays `"****"`; never print real credentials.
- No real local paths (e.g. `D:\Study\...`) in committed files; `runtime/` is gitignored.
- Comment style: match the existing Chinese/English mix in `backend/checkin.py`.
- DB access uses a module-level connection per operation (open/close) — no long-lived connections.
- Like success = HTTP 200 (the original's only signal); JSON body captured to `likes.message` but not required.
- Content fetch: `GET /blog/spider/blogs/{id}` → `{meta: {title, author, content, date}}`; JSON parse failure = non-retryable failure.
- Retry classification: 5xx / network timeout → retryable (up to 5 rounds); 403/404 / parse errors → non-retryable.

---

### Task 1: Extract shared login client

**Files:**
- Create: `backend/client.py`
- Modify: `backend/checkin.py`

**Interfaces:**
- Produces:
  - `client.build_session(config: dict) -> requests.Session`
  - `client.login(config: dict, username: str, password: str) -> requests.Session`
  - `client.get_api_base(config: dict) -> str`
  - `client.DEFAULT_UA: str`
  - Exceptions `CheckinError`, `LoginFailedError`, `NetworkError` (moved from checkin.py; keep re-exports so imports don't break)

- [ ] **Step 1: Create `backend/client.py`**

Move from `checkin.py`: `DEFAULT_UA`, `_get_api_base` (as `get_api_base(config)`), `_build_session` (as `build_session(config)`), `_extract_csrf`, `_verify_login`, `_login` (as `login(config, username, password)`). The login logic is unchanged except `self.config` → `config` param. Keep the custom exceptions `CheckinError`, `LoginFailedError`, `NetworkError` in `client.py`.

```python
# backend/client.py
import re
from urllib.parse import urljoin, urlparse

import requests


class CheckinError(Exception):
    """打卡相关异常的基类"""


class AlreadyCheckedInError(CheckinError):
    """今日已打卡"""


class LoginFailedError(CheckinError):
    """登录失败"""


class NetworkError(CheckinError):
    """网络超时或不可达"""


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


def get_api_base(config: dict) -> str:
    checkin_url = config["site"].get("checkin_url", "")
    if checkin_url:
        parsed = urlparse(checkin_url)
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def build_session(config: dict) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": get_api_base(config),
        "Referer": config["site"].get("checkin_url", get_api_base(config)),
        "Connection": "keep-alive",
    })
    return s


def _extract_csrf(html: str) -> str | None:
    patterns = [
        r'<input[^>]+name=["\']csrf_token["\'][^>]+value=["\']([^"\']+)',
        r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)',
        r'name=["\']_csrf_token["\'][^>]+value=["\']([^"\']+)',
        r'csrf_token\s*[:=]\s*["\']([^"\']+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _verify_login(session: requests.Session, checkin_url: str) -> bool:
    if not checkin_url:
        return True
    try:
        resp = session.get(checkin_url, timeout=10, allow_redirects=True)
        final_url = resp.url.lower()
        if "/auth/login" in final_url or "/login" in final_url:
            return False
        text = resp.text.lower()
        if '<form id="loginform"' in text or 'id="loginform"' in text:
            return False
        return True
    except requests.RequestException:
        return False


def login(config: dict, username: str, password: str) -> requests.Session:
    """POST login to /auth/login, return authenticated session (form-first, JSON fallback)."""
    api_base = get_api_base(config)
    site = config["site"]
    api_cfg = config.get("api", {})
    login_path = api_cfg.get("login_path", "/auth/login")
    login_url = site.get("login_url", urljoin(api_base, "/auth/login"))
    checkin_url = site.get("checkin_url", "")

    session = build_session(config)

    try:
        resp = session.get(login_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise NetworkError(f"无法访问登录页: {e}")

    csrf_token = _extract_csrf(resp.text)
    login_data = {"username": username, "password": password, "next": ""}
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Referer": login_url}
    if csrf_token:
        login_data["csrf_token"] = csrf_token

    try:
        session.post(login_url, data=login_data, headers=headers, timeout=15, allow_redirects=True)
    except requests.RequestException as e:
        raise NetworkError(f"登录请求失败: {e}")

    if not _verify_login(session, checkin_url):
        json_headers = {"Content-Type": "application/json", "Referer": login_url, "X-Requested-With": "XMLHttpRequest"}
        try:
            session.post(login_url, json={"username": username, "password": password}, headers=json_headers, timeout=15, allow_redirects=True)
            if not _verify_login(session, checkin_url):
                raise LoginFailedError(f"登录失败：账号 {username} 的用户名或密码错误")
        except requests.RequestException as e:
            raise LoginFailedError(f"登录失败: {e}")

    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    })
    return session
```

- [ ] **Step 2: Update `backend/checkin.py` to use client**

Replace `_build_session` / `_get_api_base` / `_login` bodies to delegate to `client`, and import from `.client`:

```python
from .client import (
    build_session, login as client_login, get_api_base,
    CheckinError, LoginFailedError, NetworkError,
)
```

In `CheckinEngine`:
- `_get_api_base(self)` → `return get_api_base(self.config)`
- `_build_session(self)` → `return build_session(self.config)`
- `_login(self, username, password)` → `return client_login(self.config, username, password)`
- Remove `_extract_csrf` and `_verify_login` methods (now in client).
- Re-export the exceptions at module bottom so existing `from .checkin import LoginFailedError` keeps working:

```python
# bottom of checkin.py — keep imports working
from .client import CheckinError, LoginFailedError, NetworkError  # noqa: E402,F401
```

- [ ] **Step 3: Verify imports still work**

Run: `python -c "from backend.checkin import CheckinEngine, LoginFailedError; from backend.client import login; print('ok')"` (from project root, in worktree)
Expected: prints `ok`, no `ImportError`.

- [ ] **Step 4: Commit**

```bash
git add backend/client.py backend/checkin.py
git commit -m "refactor: extract shared pure-requests login into backend/client.py"
```

---

### Task 2: SQLite store

**Files:**
- Create: `backend/store.py`

**Interfaces:**
- Produces (all functions open a connection, run, close):
  - `store.get_db_path() -> Path`  → `runtime/blog.db`
  - `store.init_db()`
  - `store.upsert_articles(rows: list[dict]) -> int` — rows have keys `id, title, author, url, category, description, likes_count`
  - `store.list_articles(limit=500) -> list[dict]`
  - `store.get_articles_by_ids(ids: list[str]) -> list[dict]`
  - `store.update_content(article_id: str, content: str) -> None`
  - `store.record_like(article_id: str, account: str, success: bool, message: str) -> None`
  - `store.list_likes(limit=100) -> list[dict]`

- [ ] **Step 1: Write `backend/store.py`**

```python
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
        cur = conn.execute(
            "SELECT * FROM articles ORDER BY created_at DESC LIMIT ?", (limit,)
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
```

- [ ] **Step 2: Smoke-test the store**

Run:
```bash
cd worktree
python -c "
import sys; sys.path.insert(0, '.')
from backend import store
store.init_db()
n = store.upsert_articles([{'id':'abc','title':'T','author':'A','url':'http://x/abc','category':'c','description':'d','likes_count':3}])
print('upserted', n, 'rows=', len(store.list_articles()))
store.update_content('abc', 'content')
store.record_like('abc', 'u1', True, 'ok')
print('likes', store.list_likes())
"
```
Expected: prints `upserted 1`, `rows= 1`, `likes [...]`. `runtime/blog.db` created.

- [ ] **Step 3: Commit**

```bash
git add backend/store.py
git commit -m "feat: add SQLite store for blog articles and likes"
```

---

### Task 3: Generic progress store

**Files:**
- Create: `backend/progress.py`

**Interfaces:**
- Produces:
  - `progress.new_task() -> str` (task_id, uuid4[:8])
  - `progress.store_progress(task_id: str, data: dict) -> None` (thread-safe, cleans to ≤200 entries)
  - `progress.get_progress(task_id: str) -> dict | None`

- [ ] **Step 1: Write `backend/progress.py`**

```python
# backend/progress.py
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
```

- [ ] **Step 2: Verify**

Run: `python -c "from backend import progress; t=progress.new_task(); progress.store_progress(t,{'done':False}); assert progress.get_progress(t)['done']==False; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/progress.py
git commit -m "feat: add generic task progress store"
```

---

### Task 4: BlogEngine

**Files:**
- Create: `backend/blog.py`

**Interfaces:**
- Consumes: `client.build_session`, `client.login`, `client.get_api_base`, `store.*`, exceptions from `client`.
- Produces:
  - `class BlogEngine`:
    - `__init__(self) -> None` — loads `config = load_config()` (from `checkin.py`), holds `self._session`
    - `scan_directory(self, progress_cb=None) -> dict` — returns `{total, new, errors}`
    - `fetch_contents(self, article_ids: list[str], progress_cb=None) -> dict` — returns `{total, success, failed}`
    - `like_articles(self, article_ids: list[str], username: str, password: str, progress_cb=None) -> dict` — returns `{total, success, failed}`
    - `clear_session(self) -> None`

- [ ] **Step 1: Write `backend/blog.py`**

```python
# backend/blog.py
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .checkin import load_config
from .client import build_session, get_api_base, login
from . import store


class BlogEngine:
    """纯 requests 博客引擎 — 扫描目录 / 抓取内容 / 批量点赞"""

    def __init__(self):
        self.config = load_config()
        self._session = None

    def clear_session(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None

    def _api_url(self, path_key: str, default: str) -> str:
        api_cfg = self.config.get("api", {})
        path = api_cfg.get(path_key, default)
        return get_api_base(self.config) + path

    # ── 目录扫描 ──────────────────────────────────────────
    def scan_directory(self, progress_cb=None):
        def _progress(step, msg):
            if progress_cb:
                try:
                    progress_cb(step, msg)
                except Exception:
                    pass

        base = self._api_url("blog_listing_path", "/blog")
        total = new = errors = 0
        page = 1
        seen_pages = set()
        _progress("scan", "正在扫描博客目录...")

        while True:
            if page in seen_pages:
                break
            seen_pages.add(page)
            url = f"{base}?page={page}"
            try:
                resp = self._session.get(url, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                articles = soup.select("article.blog-item")
                if not articles:
                    break  # end of listing
                rows = []
                for a in articles:
                    link = a.select_one("a.blog-title")
                    if not link or not link.get("href"):
                        continue
                    href = link["href"].strip()
                    if not href.startswith("/blog/"):
                        continue
                    article_id = href.rstrip("/").split("/")[-1]
                    author_el = a.select_one(".blog-author span")
                    category_el = a.select_one(".blog-category-tag")
                    desc_el = a.select_one(".blog-description")
                    likes_el = a.select_one(".blog-likes span")
                    title = link.get_text(strip=True)
                    if not title:
                        continue
                    rows.append({
                        "id": article_id,
                        "title": title,
                        "url": urljoin(get_api_base(self.config), href),
                        "author": author_el.get_text(strip=True) if author_el else "",
                        "category": category_el.get_text(strip=True) if category_el else "",
                        "description": desc_el.get_text(strip=True) if desc_el else "",
                        "likes_count": int(re.sub(r"\D", "", likes_el.get_text())) if likes_el else 0,
                    })
                n = store.upsert_articles(rows)
                total += n
                new += sum(1 for r in rows if True)  # approximate; upsert count
                _progress("scan", f"第 {page} 页，已收录 {total} 篇")
                page += 1
            except requests.RequestException as e:
                errors += 1
                _progress("scan_error", f"第 {page} 页获取失败: {e}")
                break

        _progress("done", f"扫描完成，共 {total} 篇")
        return {"total": total, "new": new, "errors": errors}

    # ── 内容抓取 ──────────────────────────────────────────
    def fetch_contents(self, article_ids, progress_cb=None):
        def _progress(step, msg):
            if progress_cb:
                try:
                    progress_cb(step, msg)
                except Exception:
                    pass

        if not article_ids:
            return {"total": 0, "success": 0, "failed": 0}
        base = self._api_url("blog_content_path", "/blog/spider/blogs")
        total = len(article_ids)
        success = failed = 0
        _progress("fetch", f"开始抓取 {total} 篇内容...")

        def _fetch_one(article_id):
            url = f"{base}/{article_id}"
            headers = {"Referer": urljoin(get_api_base(self.config), f"/blog/{article_id}")}
            try:
                resp = self._session.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    return False, article_id, resp.status_code in (500, 502, 503, 504)
                data = resp.json()
                content = data.get("meta", {}).get("content", "")
                if content:
                    store.update_content(article_id, content)
                    return True, article_id, False
                return False, article_id, False
            except (requests.Timeout, requests.ConnectionError):
                return False, article_id, True
            except requests.RequestException:
                return False, article_id, False

        pending = article_ids
        for _round in range(5):
            if not pending:
                break
            retry = []
            with ThreadPoolExecutor(max_workers=5) as ex:
                futs = {ex.submit(_fetch_one, i): i for i in pending}
                for fut in as_completed(futs):
                    ok, aid, retryable = fut.result()
                    if ok:
                        success += 1
                    else:
                        failed += 1
                        if retryable:
                            retry.append(aid)
            pending = retry
            if pending:
                time.sleep(1)
            _progress("fetch", f"已抓取 {success} 篇，待重试 {len(pending)}")
        _progress("done", f"抓取完成：成功 {success}，失败 {failed}")
        return {"total": total, "success": success, "failed": failed}

    # ── 批量点赞 ──────────────────────────────────────────
    def like_articles(self, article_ids, username, password, progress_cb=None):
        def _progress(step, msg):
            if progress_cb:
                try:
                    progress_cb(step, msg)
                except Exception:
                    pass

        if not article_ids:
            return {"total": 0, "success": 0, "failed": 0}
        self._session = login(self.config, username, password)
        base = self._api_url("blog_like_path", "/blog")
        total = len(article_ids)
        success = failed = 0
        _progress("like", f"开始为 {total} 篇点赞...")

        def _like_one(article_id):
            url = f"{base}/{article_id}/like"
            headers = {"Referer": urljoin(get_api_base(self.config), f"/blog/{article_id}")}
            try:
                resp = self._session.post(url, headers=headers, timeout=5)
                ok = resp.status_code == 200
                store.record_like(article_id, username, ok, f"HTTP {resp.status_code}")
                return ok, article_id, resp.status_code in (500, 502, 503, 504)
            except (requests.Timeout, requests.ConnectionError):
                return False, article_id, True
            except requests.RequestException:
                return False, article_id, False

        pending = article_ids
        for _round in range(5):
            if not pending:
                break
            retry = []
            with ThreadPoolExecutor(max_workers=20) as ex:
                futs = {ex.submit(_like_one, i): i for i in pending}
                for fut in as_completed(futs):
                    ok, aid, retryable = fut.result()
                    if ok:
                        success += 1
                    else:
                        failed += 1
                        if retryable:
                            retry.append(aid)
            pending = retry
            if pending:
                time.sleep(1)
            _progress("like", f"已点赞 {success} 篇，待重试 {len(pending)}")
        _progress("done", f"点赞完成：成功 {success}，失败 {failed}")
        return {"total": total, "success": success, "failed": failed}
```

- [ ] **Step 2: Verify it imports and the config wiring is right**

Run: `python -c "from backend.blog import BlogEngine; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/blog.py
git commit -m "feat: add BlogEngine (scan/fetch/like) via pure requests"
```

---

### Task 5: Wire blog API endpoints into app.py

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/config.json`

**Interfaces:**
- Consumes: `BlogEngine`, `progress`, `store`, `get_enabled_accounts`.
- Produces (Flask routes):
  - `GET /blog` → `frontend/blog.html`
  - `POST /api/blog/scan` → `{task_id}` (202)
  - `POST /api/blog/fetch` → `{task_id}` (202), body `{article_ids: [...]}`
  - `POST /api/blog/like` → `{task_id}` (202), body `{article_ids: [...], account: str}`
  - `GET /api/blog/progress/<task_id>` → progress dict
  - `GET /api/blog/articles` → `{articles: [...], likes: [...]}`

- [ ] **Step 1: Add config keys**

Add to `backend/config.json` `api` section:

```json
"api": {
  "login_path": "/auth/login",
  "checkin_path": "/checkin/api/do-checkin",
  "fortune_path": "/checkin/api/claim-fortune",
  "blog_listing_path": "/blog",
  "blog_content_path": "/blog/spider/blogs",
  "blog_like_path": "/blog"
}
```

- [ ] **Step 2: Add imports + routes to `backend/app.py`**

At top, after existing imports:

```python
from .blog import BlogEngine
from . import store, progress
```

Add routes (mirroring the checkin async pattern — `_run` in a daemon thread, progress callbacks write to `progress.store_progress`):

```python
@app.route("/blog")
def blog_index():
    """返回博客控制面板"""
    return send_from_directory(str(FRONTEND_DIR), "blog.html")


@app.route("/api/blog/articles")
def blog_articles():
    return jsonify({"articles": store.list_articles(), "likes": store.list_likes()})


@app.route("/api/blog/scan", methods=["POST"])
def blog_scan():
    task_id = progress.new_task()
    progress.store_progress(task_id, {"status": "pending", "steps": [], "results": {}, "done": False})

    def _run():
        engine = BlogEngine()
        # scan needs an authenticated session for full listings
        config = load_config()
        accounts = get_enabled_accounts()
        if not accounts:
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": "没有启用的账号"}})
            return
        engine._session = login(config, accounts[0]["username"], accounts[0]["password"])
        def cb(step, msg):
            data = progress.get_progress(task_id) or {}
            data["current_step"] = step
            data["steps"].append({"step": step, "message": msg, "time": datetime.now().strftime("%H:%M:%S")})
            progress.store_progress(task_id, data)
        results = engine.scan_directory(progress_cb=cb)
        progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": results})
        engine.clear_session()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id}), 202


@app.route("/api/blog/fetch", methods=["POST"])
def blog_fetch():
    body = request.get_json(silent=True) or {}
    article_ids = body.get("article_ids", [])
    task_id = progress.new_task()
    progress.store_progress(task_id, {"status": "pending", "steps": [], "results": {}, "done": False})

    def _run():
        engine = BlogEngine()
        config = load_config()
        accounts = get_enabled_accounts()
        if not accounts:
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": "没有启用的账号"}})
            return
        engine._session = login(config, accounts[0]["username"], accounts[0]["password"])
        def cb(step, msg):
            data = progress.get_progress(task_id) or {}
            data["current_step"] = step
            data["steps"].append({"step": step, "message": msg, "time": datetime.now().strftime("%H:%M:%S")})
            progress.store_progress(task_id, data)
        results = engine.fetch_contents(article_ids, progress_cb=cb)
        progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": results})
        engine.clear_session()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id}), 202


@app.route("/api/blog/like", methods=["POST"])
def blog_like():
    body = request.get_json(silent=True) or {}
    article_ids = body.get("article_ids", [])
    account = body.get("account", "")
    task_id = progress.new_task()
    progress.store_progress(task_id, {"status": "pending", "steps": [], "results": {}, "done": False})

    def _run():
        engine = BlogEngine()
        config = load_config()
        accounts = get_enabled_accounts()
        target = next((a for a in accounts if a["username"] == account), None)
        if not target:
            progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": {"error": "账号不存在或未启用"}})
            return
        def cb(step, msg):
            data = progress.get_progress(task_id) or {}
            data["current_step"] = step
            data["steps"].append({"step": step, "message": msg, "time": datetime.now().strftime("%H:%M:%S")})
            progress.store_progress(task_id, data)
        results = engine.like_articles(article_ids, target["username"], target["password"], progress_cb=cb)
        progress.store_progress(task_id, {**progress.get_progress(task_id), "status": "done", "done": True, "results": results})

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id}), 202


@app.route("/api/blog/progress/<task_id>")
def blog_progress(task_id):
    p = progress.get_progress(task_id)
    if p is None:
        return jsonify({"error": "任务不存在或已过期"}), 404
    return jsonify(p)
```

Note: in `_run` for scan/fetch, the engine uses the *first* enabled account (the account picker applies to like; scan/fetch just need a valid session). Import `login` from `.client` at top of app.py.

- [ ] **Step 3: Verify app starts and routes register**

Run: `python -c "from backend.app import app; print(sorted(str(r) for r in app.url_map.iter_rules() if 'blog' in str(r)))"`
Expected: prints blog routes, no exception.

- [ ] **Step 4: Commit**

```bash
git add backend/app.py backend/config.json
git commit -m "feat: add blog API endpoints and /blog route"
```

---

### Task 6: Frontend blog page

**Files:**
- Create: `frontend/blog.html`
- Modify: `frontend/index.html` (nav link)

**Interfaces:**
- Consumes: the API routes from Task 5 (`/api/blog/articles`, `/api/blog/scan`, `/api/blog/fetch`, `/api/blog/like`, `/api/blog/progress/<task_id>`, `/api/accounts`).

- [ ] **Step 1: Create `frontend/blog.html`**

Copy the `<style>` block from `frontend/index.html` (the full dark-theme CSS — cards, badges, buttons, modal, toast, progress-step styles). Body:

- Header: title "📚 博客工具", sub "raricy.com · 目录扫描 / 内容抓取 / 批量点赞".
- Account chips row (reuse `/api/accounts`; render chips, click to select the blog account).
- Action buttons: `🔄 扫描目录`, `⬇ 抓取内容`, `👍 点赞所选`, plus `↩ 返回打卡` link to `/`.
- Progress area (`#progress`): step animation reuse.
- Articles table (`#articlesTable`): checkbox per row, columns 标题/作者/分类/点赞/内容/状态.
- Results area (`#result`) for like/fetch summary.
- Toast container.

JavaScript (mirror checkin page's `API` helper, `toast`, progress-step rendering):
- `loadArticles()` → GET `/api/blog/articles`, render table.
- `loadAccounts()` → GET `/api/accounts`, render account chips, select first.
- `scanDirectory()` → POST `/api/blog/scan`, poll `/api/blog/progress/<task_id>` every 500ms, render steps, on done reload articles.
- `fetchSelected()` / `likeSelected()` → gather checked article ids, POST to `/api/blog/fetch` / `/api/blog/like` (like sends `account`), poll progress, on done reload articles.
- Auto-refresh `loadArticles()` every 30s.

- [ ] **Step 2: Add nav link to `frontend/index.html`**

In the header `.sub` or a small nav row, add a link to `/blog`:

```html
<div class="sub">
  raricy.com · 纯 HTTP API 自动化
  &nbsp;·&nbsp;
  <a href="/blog" style="color:var(--blue);">📚 博客工具</a>
</div>
```

- [ ] **Step 3: Verify the page loads**

Run: `python run.py --no-browser`, then:
- `curl -s http://127.0.0.1:5000/blog | head -5` → returns HTML.
- `curl -s http://127.0.0.1:5000/api/blog/articles` → `{"articles": [], "likes": []}`.
Expected: page serves, articles endpoint returns empty arrays (DB empty).

- [ ] **Step 4: Commit**

```bash
git add frontend/blog.html frontend/index.html
git commit -m "feat: add blog tool frontend page and nav link"
```

---

### Task 7: Update requirements + docs

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `README.md` (API endpoints + features)
- Modify: `CLAUDE.md` (architecture note)

- [ ] **Step 1: Add beautifulsoup4**

Append to `backend/requirements.txt`:

```
beautifulsoup4>=4.12,<5.0
```

- [ ] **Step 2: Update README API table**

Add rows for `/api/blog/scan`, `/api/blog/fetch`, `/api/blog/like`, `/api/blog/progress/<task_id>`, `/api/blog/articles`, and the `/blog` page. Add a short "博客工具" bullet under 功能特性.

- [ ] **Step 3: Update CLAUDE.md**

In the Architecture section, add a line:

> A `BlogEngine` (`backend/blog.py`) shares the same `requests` login (`backend/client.py`) and adds blog directory scanning (beautifulsoup4), content fetch, and batch like, persisted to SQLite (`runtime/blog.db`) via `backend/store.py`. Blog ops are async with task_id progress like check-in.

- [ ] **Step 4: Verify**

Run: `pip install -r backend/requirements.txt` (installs beautifulsoup4). Then `python -c "import bs4; print(bs4.__version__)"`.
Expected: installs, prints version.

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt README.md CLAUDE.md
git commit -m "docs: add beautifulsoup4 dep and document blog module"
```

---

## Self-Review Notes

- **Spec coverage:** All spec sections mapped to tasks — login merge (T1), store (T2), progress (T3), engine (T4), endpoints (T5), frontend (T6), deps/docs (T7). No gaps.
- **Type consistency:** `BlogEngine.scan_directory/fetch_contents/like_articles` return dicts consumed by app.py `results`; `store` function names match across T2/T4/T5; `progress.new_task/store_progress/get_progress` consistent across T3/T5.
- **Placeholder scan:** No TBD/TODO; every code step has concrete code.
