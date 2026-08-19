# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

There are no tests, linters, or build steps in this project.

### Windows-specific pitfalls

- `start_checkin.bat` must stay **pure ASCII**. Chinese characters get mangled by cmd's GBK codepage, so the bat contains only English text and `%~dp0` (no hardcoded path).
- The bat sets `PYTHONIOENCODING=utf-8` because run.py's emoji banner raises `UnicodeEncodeError` when stdout is redirected. Keep this env var if you touch the launcher.
- No real local paths (e.g. `D:\Study\...`) appear in committed files — README uses placeholders, the bat uses `%~dp0`. Keep it that way.
- The `一键打卡.lnk` shortcut is created manually on the desktop (PowerShell `WScript.Shell`), not in the repo.

## Architecture

This is an automated check-in (打卡) system for raricy.com — a Flask web server + APScheduler. The entire flow uses pure `requests` HTTP calls — **zero Selenium/ChromeDriver dependency**.

**Data flow (check-in cycle):**
`APScheduler cron tick` or `POST /api/checkin` (async) → `CheckinEngine.execute()` → `requests.Session` POST `/auth/login` → POST `/checkin/api/do-checkin` → optionally POST `/checkin/api/claim-fortune` → write JSON log entry

> A `BlogEngine` (`backend/blog.py`) shares the same `requests` login (`backend/client.py`) and adds blog directory scanning (beautifulsoup4), content fetch, and batch like, persisted to SQLite (`runtime/blog.db`) via `backend/store.py`. Blog ops are async with task_id progress like check-in.

**Key architectural decisions:**

- **Pure requests, no browser.** Login is a form POST to `/auth/login` with `username` + `password` (tries form-data first, falls back to JSON). Login verification checks whether accessing the checkin URL redirects to `/auth/login`. The authenticated `requests.Session` is reused for the checkin API call. This eliminates Chrome/ChromeDriver version management entirely.
- **`api` config section.** `config.json` includes `api.login_path` (`/auth/login`), `api.checkin_path` (`/checkin/api/do-checkin`), `api.fortune_path` (`/checkin/api/claim-fortune`), and the blog paths `api.blog_listing_path` / `api.blog_content_path` / `api.blog_like_path`. All paths are relative to the base URL from `site.checkin_url`; blog.py and checkin.py read them via `load_config()` on each operation.
- **Async progress tracking.** `POST /api/checkin` returns a `task_id` immediately (HTTP 202), then the frontend polls the progress endpoint every 500ms while a task runs. Check-in progress lives in an in-memory dict in `app.py` (`_checkin_progress`, capped at 200 entries); blog tasks use the shared `backend/progress.py` (thread-safe with a Lock, same ~200-entry cap) and arm `progress.watchdog()` so a hung task is force-marked "done with error" instead of hanging the UI (15 min for scans/fetches/likes).
- **Per-account engine instances.** Each check-in creates a fresh `CheckinEngine` instance (in both scheduler and async API thread). Each `execute()` call builds a new `requests.Session` via `_build_session()`. No state leaks between accounts.
- **Config is the shared contract.** `backend/config.json` is read fresh by both `CheckinEngine` and `CheckinScheduler` on each operation via `load_config()`. All editing happens in the `/config` panel (`frontend/config.html`) — it reads via `GET /api/config` (passwords masked as `****`) and writes via `POST /api/config` / `POST /api/accounts`; every write saves to disk then calls `scheduler.restart()` so schedule changes apply immediately.
- **Scheduler singleton.** `scheduler.get_scheduler()` returns a module-level `CheckinScheduler` instance. `use_reloader=False` in `run.py` is mandatory — otherwise the reloader spawns a second process with a duplicate scheduler.
- **Logs are a JSON file.** `runtime/logs/checkin_log.json` stores an array. `read_logs()` reads the entire file, sorts by timestamp descending, slices to limit.
- **Frontend is a multi-page vanilla HTML console.** Four panels — `frontend/index.html` (控制中心), `checkin.html` (自动打卡), `blog.html` (博客工具), `config.html` (系统配置) — share `styles.css`, `app.js` (API client / toast / nav highlight), and `bg.js` (particle starfield + meteors). No bundler, no framework. Panels auto-refresh every 10 minutes, skipping while a task poll is running so progress isn't clobbered.
- **Password masking.** API returns `"****"`; saving `"****"` preserves the original.

## Multi-account support

Accounts live in `backend/accounts.json` (gitignored — passwords are never committed), as an array of `{username, password, enabled}`. `load_config()` in `checkin.py` reads `config.json`, then overwrites `config["accounts"]` from `accounts.json`; if `accounts.json` is missing it falls back to a legacy `accounts` array embedded in `config.json`. Writes go the opposite way: `save_config()` in `app.py` pops `accounts` out of the config and routes them to `save_accounts()`. Accounts with `enabled: false` are skipped.

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

## iOS app

`ios/` is a native **SwiftUI** port of the check-in flow (manual check-in + fortune + multi-account). Zero third-party dependencies; no background scheduling (iOS can't guarantee unattended cron). It talks to the same raricy.com endpoints and does not touch the Flask backend.

- `ios/RaricyCheckin/` — SwiftUI sources (Views / ViewModels / Engine / Networking / Storage); endpoints are hardcoded in `Config/AppConfig.swift` (`https://raricy.com`).
- `ios/README.md` — local build via `xcodegen generate` (or manual project creation in Xcode 15+).
- `ios/DEPLOY.md` — the **verified no-Mac install path**: push to `main` → GitHub Actions cloud build (`.github/workflows/build-ipa.yml`, unsigned `.ipa` uploaded as artifact) → Windows iLoader "Import IPA" to sign & install. Documents the dead ends too (AltStore / SideStore both fail on iPhone 17 / iOS 26; 7-day free-Apple-ID re-sign limit, manual reinstall each week).
- The `.ipa` build triggers automatically on `main` pushes; manual trigger via Actions → "Build iOS IPA" → Run workflow.

## Adjacent directories (not part of the check-in system)

- `raricy/` — downloaded HTML snapshots of raricy.com pages (login/checkin/blog/article/index) kept for reference when inspecting the site's markup. Not served or executed.
- The old standalone Selenium auto-like bot (`like_bot/`, never committed) is superseded by `backend/blog.py` + `backend/store.py`, which use beautifulsoup4, not Selenium. Don't mistake old scripts for the integrated module, and don't add Selenium to `backend/requirements.txt`.
