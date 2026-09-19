# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r backend/requirements.txt

# Start the system (Flask + APScheduler)
python run.py                  # default port 5000, auto-opens browser
python run.py --port 8080      # custom port
python run.py --host 0.0.0.0   # bind address (default 127.0.0.1)
python run.py --debug          # Flask debug mode (hot reload; use_reloader stays off)
python run.py --no-browser     # skip opening browser

# One-click desktop launch: desktop shortcut -> start_checkin.bat -> launcher.py -> run.py
python launcher.py             # discovers the running server on any port (checks 5000 first,
                               # then scans run.py processes' listening ports), starts the server
                               # if down, otherwise just opens the panel
```

There are no linters or build steps. There is one small test suite: `tests/` uses the standard library `unittest` only (no pytest, no new dependencies) and covers the account-encryption layer — the part where a mistake destroys credentials silently. Run it from the repo root:

```bash
python -m unittest discover -s tests -t .
```

`tests/__init__.py` must stay — Python 3.11 dropped namespace-package discovery, so without it the command fails with `ImportError: Start directory is not importable`.

## Docker / 服务器部署

The Flask app runs in a container on Rocky Linux 9; the full runbook is `deploy/DEPLOY.md`. **The server builds the image from source** — no image tarball travels over the wire any more:

```bash
# 服务器上，首次
sudo mkdir -p /opt/raricy/data /opt/raricy/key
git clone https://github.com/yao1145/raricy_auto_checkin.git /opt/raricy/app
# …按 DEPLOY.md 灌入 data/ 与 key/，然后
cd /opt/raricy/app && sudo docker compose up -d --build

# 以后的每次更新
cd /opt/raricy/app && git pull && sudo docker compose up -d --build
```

Four constraints that are not negotiable:

- **Single process only.** The app is `Flask + in-process APScheduler`. **Never put gunicorn/uvicorn with multiple workers in front of it** — every worker starts its own scheduler and every account gets checked in repeatedly. `use_reloader=False` in `run.py` exists for the same reason. The Dockerfile deliberately runs `python run.py` directly.
- **The container binds `0.0.0.0`, the host port binds `127.0.0.1`.** Binding `127.0.0.1` *inside* the container makes the published port unreachable (container loopback ≠ host loopback). The loopback restriction is enforced by `docker-compose.yml`'s `127.0.0.1:5000:5000`.
- **No authentication on the panel.** Anyone who can reach the port can read the account list, trigger check-ins, rewrite config and delete accounts. That is why the port is published to host loopback only and access goes through an SSH tunnel.
- **Only directory bind mounts, never single files.** A single-file bind mount is a mount point, and Linux `rename(2)` refuses to replace a mount point — it returns `EBUSY`. `accounts.enc` is written with `.tmp` + `os.replace`, so mounting it as a single file makes **every** panel save return HTTP 500, while the same code runs fine under local `python run.py`. Mutable paths are injectable through `RARICY_DATA_DIR` / `RARICY_RUNTIME_DIR` / `RARICY_KEY_PATH` (`backend/paths.py`, defaults = the local layout); `tests/test_deploy_mounts.py` enforces the directory-only rule.

Build notes for networks that can't reach Docker Hub / PyPI (common in China), neither of which puts a mirror URL in the repo:

- Base image: set `registry-mirrors` in `/etc/docker/daemon.json` on the server (or one-off `docker save` / `docker load` of `python:3.13-slim`).
- pip: the Dockerfile defaults to the Tsinghua mirror via `ARG PIP_INDEX_URL`; override with `docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`.

### Windows-specific pitfalls

- `start_checkin.bat` must stay **pure ASCII**. Chinese characters get mangled by cmd's GBK codepage, so the bat contains only English text and `%~dp0` (no hardcoded path).
- The bat sets `PYTHONIOENCODING=utf-8` because run.py's emoji banner raises `UnicodeEncodeError` when stdout is redirected. Keep this env var if you touch the launcher.
- No real local paths (e.g. `D:\Study\...`) appear in committed files — README uses placeholders, the bat uses `%~dp0`. Keep it that way.
- The `一键打卡.lnk` shortcut is created manually on the desktop (PowerShell `WScript.Shell`), not in the repo.

## Architecture

This is an automated check-in (打卡) system for raricy.com — a Flask web server + APScheduler. The entire flow uses pure `requests` HTTP calls — **zero Selenium/ChromeDriver dependency**.

**The target site is Next.js, not Flask (rewritten around 2026-09).** Everything lives under `/api/*`, request bodies are JSON, field names are camelCase, and the session is a JWT cookie (`raricy_session`, 30 days). The old `/auth/login`, `/checkin/api/*` and `/blog/spider/blogs` paths now return 404. **The site's source code is public at `github.com/raricycms/raricy.com` (linked in its own footer) — when an endpoint changes, read the route file there (`src/app/api/...`, `src/lib/rate-limit.ts`, `src/lib/session.ts`) instead of guessing or packet-sniffing.**

**Data flow (check-in cycle):**
`APScheduler cron tick` or `POST /api/checkin` (async) → `CheckinEngine.execute()` → `requests.Session` POST `/api/auth/login` → POST `/api/checkin` → optionally POST `/api/checkin/claim` → write JSON log entry

> A `BlogEngine` (`backend/blog.py`) shares the same `requests` login (`backend/client.py`) and adds blog listing scan (`GET /api/blogs`, JSON with a `pagination` object), content fetch (`GET /api/spider/blogs/<id>` — the Markdown lives in the **top-level** `content` field), and batch like (`POST /api/blogs/<id>/like`), persisted to SQLite (`runtime/blog.db`) via `backend/store.py`. Article ids are UUIDs now, not integers. Blog ops are async with task_id progress like check-in.

**Key architectural decisions:**

- **Pure requests, no browser.** Login is a JSON POST to `/api/auth/login` with `{username, password}` (username or email both work); the site replies `{code, message, user}` and sets the session cookie. Failures come back as `401` (bad credentials) or `429` (rate limited — the site counts **failed attempts only**: 100 per 15 min per username, 300 per 15 min per IP) and are surfaced as `LoginFailedError` vs `RateLimitedError`, so a throttled account is never reported as a wrong password. Because `code: 200` alone does not prove the cookie stuck (the site's own `session.ts` documents a silent "200 but session doesn't stick" failure when the cookie's `Secure` flag disagrees with the proxy protocol), `_verify_login()` re-checks with `GET /api/checkin`. The authenticated session is reused for the checkin API call. This eliminates Chrome/ChromeDriver version management entirely.
- **`api` config section.** `config.json` includes `api.login_path` (`/api/auth/login`), `api.checkin_path` (`/api/checkin`), `api.fortune_path` (`/api/checkin/claim`), and the blog paths `api.blog_listing_path` (`/api/blogs`) / `api.blog_content_path` (`/api/spider/blogs`) / `api.blog_like_path` (`/api/blogs`; the like URL is `<blog_like_path>/<id>/like`). All paths are resolved against the base URL from `site.checkin_url` by `client.api_url()`; `site.login_url` is now only the page URL used as `Referer`. blog.py and checkin.py read them via `load_config()` on each operation.
- **Async progress tracking.** `POST /api/checkin` returns a `task_id` immediately (HTTP 202), then the frontend polls the progress endpoint every 500ms while a task runs. Check-in progress lives in an in-memory dict in `app.py` (`_checkin_progress`, capped at 200 entries); blog tasks use the shared `backend/progress.py` (thread-safe with a Lock, same ~200-entry cap) and arm `progress.watchdog()` so a hung task is force-marked "done with error" instead of hanging the UI (15 min for scans/fetches/likes).
- **Per-account engine instances.** Each check-in creates a fresh `CheckinEngine` instance (in both scheduler and async API thread). Each `execute()` call builds a new `requests.Session` via `_build_session()`. No state leaks between accounts.
- **Config is the shared contract.** `backend/config.json` is read fresh by both `CheckinEngine` and `CheckinScheduler` on each operation via `load_config()`. All editing happens in the `/config` panel (`frontend/config.html`) — it reads via `GET /api/config` (passwords masked as `****`) and writes via `POST /api/config` / `POST /api/accounts`; every write saves to disk then calls `scheduler.restart()` so schedule changes apply immediately.
- **Scheduler singleton.** `scheduler.get_scheduler()` returns a module-level `CheckinScheduler` instance. `use_reloader=False` in `run.py` is mandatory — otherwise the reloader spawns a second process with a duplicate scheduler.
- **Logs are a JSON file.** `runtime/logs/checkin_log.json` stores an array. `read_logs()` reads the entire file, sorts by timestamp descending, slices to limit.
- **Blog likes need a core account.** `POST /api/blogs/<id>/like` answers `403 需要核心用户权限` for a plain `user` role — the API is gated at core level even though the blog page itself is reachable. The endpoint is a *toggle*: it returns `liked: true` when it liked, `liked: false` when the call actually **un**-liked, which is why `blog.py` never trusts `code: 200` alone and retries up to `MAX_LIKE_ATTEMPTS`. Server-side caps are 100/hour and 500/day per account (`src/lib/rate-limit.ts`), on top of our own `DAILY_LIKE_LIMIT`.
- **Blog content reads need a core account too.** `GET /api/spider/blogs/:id` — the endpoint returning article Markdown — was fully unauthenticated until 2026-09-18, when upstream `5eace12` put a `core+` guard on it (anonymous `401 请先登录`, plain `user` `403 需要核心用户权限`) along with `/api/spider/comments`, `/api/spider/comments/<id>`, `/api/spider/favorites/<id>` and `/api/blogs/<id>/comments`; we only call the first. Because `fetch_contents()` counts any non-200 as an ordinary per-article failure, a non-core account would turn a whole batch into a silent `成功 0，失败 N`. So `client.login()` now keeps the `user.role` from the login response (`user < core < admin < owner`, mirroring upstream `lib/auth.ts` and exposed via `session_role()` / `is_core_role()`), `fetch_contents()` refuses to start on a non-core session, and `POST /api/blog/fetch` picks its account with `login_first_core()` rather than hardcoding `accounts[0]` (the config panel can add and remove accounts but not reorder them). `GET /api/blogs` — the directory scan — is still unauthenticated, so scanning is unaffected. `tests/test_blog_core_gate.py` pins all of it.
- **Frontend is a multi-page vanilla HTML console.** Four panels — `frontend/index.html` (控制中心), `checkin.html` (自动打卡), `blog.html` (博客工具), `config.html` (系统配置) — share `styles.css`, `app.js` (API client / toast / nav highlight), and `bg.js` (particle starfield + meteors). No bundler, no framework. Panels auto-refresh every 10 minutes, skipping while a task poll is running so progress isn't clobbered.
- **Password masking.** API returns `"****"`; saving `"****"` preserves the original.
- **The account file is encrypted, and decrypt failure must never degrade to "no accounts".** `backend/crypto.py` owns key handling and Fernet primitives; `checkin.py`'s `load_accounts()` / `save_accounts()` are the only read/write points. The order is fixed: if `accounts.enc` exists, decrypt it, and on failure raise `AccountsDecryptError`; fall back to plaintext **only when the ciphertext file is absent**. Returning `[]` or `None` on a decrypt failure would mean the next save overwrites every credential, and falling back to plaintext on failure would let anyone who can write files downgrade the app to the plaintext path by dropping a file in place. `tests/test_accounts_store.py::test_corrupt_ciphertext_never_falls_back_to_plaintext` guards exactly this — do not delete it. `app.py` carries an `AccountsDecryptError` errorhandler so the failure surfaces as a clear JSON 500 instead of an empty account list.

## Multi-account support

Accounts live in **`backend/accounts.enc`** (gitignored) — Fernet-encrypted JSON, an array of `{username, password, enabled}`. The key is `runtime/.accounts.key` (gitignored, auto-generated on first save, `0o600`).

`load_config()` in `checkin.py` reads `config.json`, then overwrites `config["accounts"]` from `load_accounts()`. Writes go the opposite way: `save_config()` in `app.py` pops `accounts` out of the config and routes them to `save_accounts()`, which encrypts and writes atomically (`.tmp` + `os.replace`). Accounts with `enabled: false` are skipped. Nothing else touches the account file — `app.py` and `blog.py` only ever go through `load_config()` / `save_accounts()`, which is why the encryption change never leaked into the panel or the engines.

**`load_accounts()` has a fixed decision order that must not be reordered** (see the architectural decision below). A legacy plaintext `backend/accounts.json` is still read as a migration fallback, but only when `accounts.enc` is *absent*.

Upgrading an old checkout:

```bash
python -m backend.accounts_tool status    # read-only: what exists, does the ciphertext decrypt
python -m backend.accounts_tool encrypt   # accounts.json → accounts.enc (refuses to clobber without --force)
```

Migration is a deliberate command, never automatic at startup. Back up `runtime/.accounts.key` before deleting the plaintext — lose the key and the accounts are unrecoverable.

The `selectors` and most of `fortune` config sections are legacy and no longer used — all page interaction is via the HTTP API paths in the `api` config section. Only `fortune.enabled` and `fortune.card_index` are still read by the engine.

## API endpoints

- `GET /api/health` — health check
- `GET /api/status` — today's check-in status per account (`account_status: {username: record_or_None}`) + schedule info
- `POST /api/checkin` — async, returns `{task_id}` immediately (HTTP 202); body `{accounts: [...]}` or `{accounts: ["all"]}`
- `GET /api/checkin/progress/<task_id>` — poll for step-by-step progress
- `GET /api/logs?limit=50` — check-in history log
- `GET/POST /api/accounts` — multi-account list management (passwords masked as `****`)
- `GET/POST /api/config` — read/write config; supports dot-path (`{path, value}`) or full-object merge
- Blog: `GET /api/blog/articles` (paged), `/api/blog/articles/all`, `/api/blog/article/<id>`, `/api/blog/meta`, `/api/blog/like-stats`; `POST /api/blog/scan|fetch|like|clear` (all async except clear); `GET /api/blog/progress/<task_id>`

## Frontend behavior

- `checkin.html`: log table defaults to 5 rows, expandable to 50 via a toggle button in `<tfoot id="logExpandRow">`; the fortune column shows the result value (e.g. "大吉") not the card index; account chips above the check-in button control which accounts are selected; progress polling runs every 500ms via `setInterval`, rendering step icons (● login → ✓ logged in → ● checking → ✓ done)
- `index.html`: today's status overview + feature navigation
- `blog.html`: article table with filter/sort, fetch-and-view content, batch like with per-account daily quota (100/day, auto-disabled when exhausted)
- `config.html`: every config section (accounts / site / schedule / fortune / api) rendered as a card, saved with a single 保存配置 button at the bottom

## Adjacent directories (not part of the check-in system)

- `raricy/` — HTML snapshots of raricy.com pages (login/checkin/blog/article/index) grabbed in Aug 2026, i.e. *before* the Next.js rewrite. The site is client-rendered now, so this markup no longer matches anything live; prefer the public repo when you need the real structure.
- The old standalone Selenium auto-like bot (`like_bot/`, never committed) is superseded by `backend/blog.py` + `backend/store.py`, which are pure `requests` + `json` — neither Selenium nor, since the Next.js migration, beautifulsoup4 (the listing is a JSON API now, so that dependency was dropped from `requirements.txt`). Don't mistake old scripts for the integrated module, and don't add Selenium back.
