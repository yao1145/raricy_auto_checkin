# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r backend/requirements.txt

# Start the system (Flask + APScheduler)
python run.py                  # default port 5000, auto-opens browser
python run.py --port 8080      # custom port
python run.py --debug          # Flask debug mode (hot reload; use_reloader stays off)
python run.py --no-browser     # skip opening browser
```

There are no tests, linters, or build steps in this project.

## Architecture

This is an automated check-in (打卡) system for raricy.com — a Flask web server + APScheduler. The entire flow uses pure `requests` HTTP calls — **zero Selenium/ChromeDriver dependency**.

**Data flow (check-in cycle):**
`APScheduler cron tick` or `POST /api/checkin` (async) → `CheckinEngine.execute()` → `requests.Session` POST `/auth/login` → POST `/checkin/api/do-checkin` → optionally POST `/checkin/api/claim-fortune` → write JSON log entry

**Key architectural decisions:**

- **Pure requests, no browser.** Login is a form POST to `/auth/login` with `username` + `password` (tries form-data first, falls back to JSON). Login verification checks whether accessing the checkin URL redirects to `/auth/login`. The authenticated `requests.Session` is reused for the checkin API call. This eliminates Chrome/ChromeDriver version management entirely.

- **`api` config section.** `config.json` includes `api.login_path` (`/auth/login`), `api.checkin_path` (`/checkin/api/do-checkin`), and `api.fortune_path` (`/checkin/api/claim-fortune`). All paths are relative to the base URL from `site.checkin_url`.

- **Async progress tracking.** `POST /api/checkin` returns a `task_id` immediately (HTTP 202), then the frontend polls `GET /api/checkin/progress/<task_id>` every 500ms. Progress steps are stored in an in-memory dict (`_checkin_progress`), cleaned when exceeding 200 entries.

- **Per-account engine instances.** Each check-in creates a fresh `CheckinEngine` instance (in both scheduler and async API thread). Each `execute()` call builds a new `requests.Session` via `_build_session()`. No state leaks between accounts.

- **Config is the shared contract.** `backend/config.json` is read fresh by both `CheckinEngine` and `CheckinScheduler` on each operation via `load_config()`. API config writes (`POST /api/config`) save to disk then call `scheduler.restart()`.

- **Scheduler singleton.** `scheduler.get_scheduler()` returns a module-level `CheckinScheduler` instance. `use_reloader=False` in `run.py` is mandatory — otherwise the reloader spawns a second process with a duplicate scheduler.

- **Logs are a JSON file.** `runtime/logs/checkin_log.json` stores an array. `read_logs()` reads the entire file, sorts by timestamp descending, slices to limit.

- **Frontend is a single vanilla HTML file.** No bundler, no framework. Auto-refreshes every 30 seconds.

- **Password masking.** API returns `"****"`; saving `"****"` preserves the original.

## Multi-account support

Each account in `config.json` `accounts` array has `username`, `password`, `enabled`. The `selectors` and `fortune` config sections are legacy and no longer used — all page interaction is via the HTTP API paths in the `api` config section. Only `fortune.enabled` and `fortune.card_index` are still read by the engine.

## API endpoints added

- `POST /api/checkin` — async, returns `{task_id}` immediately (HTTP 202)
- `GET /api/checkin/progress/<task_id>` — poll for step-by-step progress
- `GET/POST /api/accounts` — multi-account list management
- `GET /api/status` now includes `account_status: {username: record_or_None}`

## Frontend behavior

- Log table defaults to 5 rows, expandable to 50 via a toggle button in `<tfoot id="logExpandRow">`
- Fortune column shows result value (e.g. "大吉") not card index
- Account chips above the checkin button control which accounts are selected
- Progress polling runs every 500ms via `setInterval`, rendering step icons (● login → ✓ logged in → ● checking → ✓ done)
