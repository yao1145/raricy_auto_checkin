# Design: Integrate like_bot into the backend as a Blog module

## Context

The repo contains two untracked working-tree directories that are *not* part of the check-in system:

- `like_bot/` — standalone Python bots (Selenium-based) for the same raricy.com site:
  - `searcher.py` — logs in via Selenium, scans the blog directory (`/blog`, server-rendered HTML), saves `admin_articles.csv` (作者, 文章链接).
  - `contents.py` — logs in via Selenium, fetches each article's content from `GET /blog/spider/blogs/{id}` (this part is already pure `requests`), saves `article_details.csv`.
  - `likes-clicker.py` — logs in via Selenium, batch-likes articles via `POST /blog/{id}/like` with multi-round retry + `ThreadPoolExecutor`.
- `raricy/` — downloaded HTML snapshots of raricy.com pages (login/checkin/blog/article) kept for reference.

**Goal:** integrate these three features into the Flask backend as a first-class "blog" module, with a new frontend page in the same style, replacing Selenium login with the existing pure-`requests` login, and merging duplicate login logic.

**User decisions (confirmed):**
1. Feature scope: **all three** — directory scan + content fetch + batch like.
2. Storage: **SQLite** (`runtime/blog.db`, stdlib `sqlite3`), not JSON/CSV.
3. HTML parsing for directory scan: **beautifulsoup4** (new dependency).
4. Frontend: **new page** `frontend/blog.html` at `/blog`, same dark theme, nav-linked from `index.html`.
5. Account for blog ops: **user picks the account** via account chips (reusing `accounts.json`), mirroring the checkin page UX.

## Approach for merging login

Extract the pure-`requests` login machinery out of `CheckinEngine` into a shared `backend/client.py`:

- `_build_session()`, `_login()`, `_verify_login()`, `_extract_csrf()` move to module-level functions:
  - `build_session(config) -> requests.Session`
  - `login(config, username, password) -> requests.Session` (form-first, JSON fallback, CSRF extraction, redirect-to-login verification)
- `CheckinEngine` and the new `BlogEngine` both call these. One login implementation; no Selenium anywhere.
- The refactor is mechanical and behavior-preserving. The checkin flow is smoke-tested after.

This satisfies "merge duplicate features (login)" directly.

## Architecture

```
Frontend blog.html ──▶ Flask routes (app.py)
                          │  async task_id + 500ms polling (same pattern as checkin)
                          ▼
                      BlogEngine (backend/blog.py)
         ┌──────────────────┼──────────────────┐
   scan_directory()   fetch_contents()    like_articles()
         │                │                  │
   GET /blog?page=N  GET /blog/spider/   POST /blog/{id}/like
   (bs4 parse)       blogs/{id}          (Referer header)
         └────────────────┼──────────────────┘
                          ▼
              client.py: login() → requests.Session   ◀── CheckinEngine uses same
                          ▼
              store.py: SQLite runtime/blog.db
```

### New backend files

- `backend/client.py` — shared `build_session(config)` + `login(config, username, password)` extracted from `checkin.py`; custom exceptions (`CheckinError`, `LoginFailedError`, `NetworkError`) also move here so both engines share them.
- `backend/blog.py` — `BlogEngine`:
  - `scan_directory(progress_cb=None)` → iterate `GET /blog?page=N` starting at page 1, parse `<article class="blog-item">` with bs4 (title/url/author/category/description/likes), upsert into DB. **Stop condition:** when a page yields zero `article.blog-item` elements (end of listing) — the pagination links are not trusted as the sole signal. Return summary.
  - `fetch_contents(article_ids=None, progress_cb=None)` → `GET /blog/spider/blogs/{id}` per article, write `content` back into DB, `ThreadPoolExecutor` + multi-round retry like original.
  - `like_articles(article_ids, account, progress_cb=None)` → `POST /blog/{id}/like` with `Referer`, per-worker sessions, `ThreadPoolExecutor` + multi-round retry, log each attempt.
  - Each `execute`-style call builds a fresh `requests.Session` via `client.login(config, username, password)` — no state leaks.
- `backend/store.py` — SQLite accessor: schema init, upserts, queries (list articles, get pending contents, record likes). DB at `runtime/blog.db`.
- `backend/progress.py` — generic task progress store (task_id → steps/results), same shape as `_checkin_progress` in `app.py`, reused by blog ops. Checkin's in-memory store is left as-is to limit risk.

### SQLite schema (`runtime/blog.db`)

```sql
CREATE TABLE IF NOT EXISTS articles (
  id TEXT PRIMARY KEY,          -- UUID path segment from URL
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
```

Scan upserts rows (`INSERT ... ON CONFLICT(id) DO UPDATE`) so re-scans don't lose fetched content or create duplicates. Fetch augments `content`. Likes log history per account.

### Config

Add to `config.json` `api` section, following the existing convention (all paths relative to base URL from `site.checkin_url`):

- `api.blog_listing_path` = `"/blog"`
- `api.blog_content_path` = `"/blog/spider/blogs"`  (article id appended)
- `api.blog_like_path` = `"/blog"`  (article id + `/like` appended)

### Frontend

- New `frontend/blog.html`, served at `/blog`, sharing the existing dark-theme CSS (`--bg`, cards, badges, buttons, modal, toast, progress-step styles).
- Nav link from `index.html` header to `/blog` (and back).
- Sections:
  - Account chips (reuse `/api/accounts`; pick which account runs blog ops).
  - "扫描目录" button → triggers `/api/blog/scan`, polls progress, renders step animation.
  - Articles table: checkbox per row, title/author/category/likes/content-status columns, from `/api/blog/articles`.
  - "抓取内容" + "点赞" for selected articles → `/api/blog/fetch`, `/api/blog/like`.
  - Like history / results toast.
- Same 500ms polling pattern as checkin.

### API endpoints (new, in app.py)

- `POST /api/blog/scan` → async task_id
- `POST /api/blog/fetch` → async task_id (body: article ids)
- `POST /api/blog/like` → async task_id (body: article ids + account)
- `GET /api/blog/progress/<task_id>` → poll progress (reuse progress.py)
- `GET /api/blog/articles` → list from DB
- `GET /blog` → frontend/blog.html

### Dependencies

- Add `beautifulsoup4` to `backend/requirements.txt`. SQLite is stdlib.

### Concurrency

- Scan/fetch/like use `ThreadPoolExecutor` (max_workers ~5–20) like the original bots.
- Unlike the original (one shared `requests.Session` across threads, not thread-safe), each worker thread gets its own session initialized from the logged-in cookie jar — safer and idempotent.
- Like result: success = HTTP 200 (the original's only signal). The JSON body is captured and stored in `likes.message` for visibility but not required for success.
- Content fetch: `GET /blog/spider/blogs/{id}` returns `{meta: {title, author, content, date}}`; a JSON parse failure is treated as a non-retryable failure for that article.

## Error handling

- `LoginFailedError` → surfaced in task results + frontend toast; login failure is not retried.
- Per-article fetch/like failures: classified into retryable (5xx/network) vs non-retryable (403/404), multi-round retry (max 5) like the original, failures written to the task result + likes table.
- Missing account / no articles selected → 400 with a clear message.

## Testing / verification

- No test framework in the repo. Verify by:
  - `pip install -r backend/requirements.txt` (adds beautifulsoup4).
  - `python run.py --no-browser` → smoke-test the existing checkin flow still works (approach A refactor).
  - Exercise the blog page: scan directory, fetch contents, like a couple of articles; confirm DB rows and progress polling.
  - Confirm `/blog` renders with the same theme.

## Non-goals

- No changes to the existing checkin flow beyond the mechanical `client.py` extraction.
- The standalone `like_bot/` scripts and `raricy/` snapshots are left untouched (out of scope for this integration).
- No new frontend framework/bundler — stays vanilla HTML like the checkin page.
