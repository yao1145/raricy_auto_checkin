# Design: Blog/checkin bug fixes — poll fallback, refresh-preserves-view, watchdog, UTF-8 decode

## Context

Two user-reported bugs on the blog tools page (and a shared pattern on the checkin page):

**Bug 1 — garbled scraped content.** Article content fetched via `_fetch_one` shows mojibake like `Narcissu жёёжҲҸгҖҺж°ҙд»ҷгҖҸж–Үжң¬пјҲKFCжұүеҢ–зүҲпјү` instead of `Narcissu 游戏『水仙』文本（KFC汉化版）`. Root cause: `resp.json()` on a charset-less `application/json` response falls back to `resp.text` → `charset_normalizer` mis-guesses UTF-8 Chinese as a single-byte Cyrillic codepage, producing a byte-perfect mojibake.

**Bug 2 — auto-refresh resets view + ongoing tasks hang.** Every ~1 min the 30s auto-refresh calls `loadArticles()` (reset=true), which wipes the loaded-all / deep-scrolled / filtered view back to page 1, losing state. Meanwhile `pollProgress` polls every 500ms with NO terminal fallback — `catch (e)` swallows 404, and if the daemon thread is stuck (site API change wedges a request, or the task is evicted from the 200-entry progress dict), `done` never flips → the poll loops forever → `_running` stays true → the auto-refresh guard blocks → the UI freezes on "processing...". The two symptoms compound.

**User decision:** fix all four parts; continue with the same design → spec → plan → subagent-driven flow.

## Fixes

### Fix A — Poll terminal fallback (`frontend/blog.html` + `frontend/index.html`)

The `pollProgress` (blog) and the inline poll (checkin `index.html`) loop forever with a swallowed catch. Add:
- **Stop on 404**: if `API.get` throws or returns 404 for the task, `clearInterval`, re-enable buttons, show an error toast ("任务已失效/不存在"), and call `_endTask`-equivalent.
- **Max duration**: a `POLL_MAX_MS` (e.g. 10 minutes = 1200 ticks at 500ms). When reached, `clearInterval`, re-enable buttons, toast "任务超时", and mark done.
- This guarantees the poll always terminates; the UI can never be frozen on "processing..." forever.

Shared constants/logic: `const POLL_MAX_MS = 600000;` and a helper `stopPoll(errorMsg)` that clears the timer, restores button state, and toasts.

### Fix B — Auto-refresh preserves the view (`frontend/blog.html`)

The 30s auto-refresh currently calls `loadArticles()` (reset). Introduce a `loadedAll` flag:
- Set `loadedAll = true` in `loadAll()` (after a successful `/all` fetch).
- In the auto-refresh callback: if `loadedAll`, re-fetch `/all` in place (`loadAll()`-style, no reset to page 1); otherwise `loadArticles()` as now.
- Clear `loadedAll` when a filter/sort change triggers a normal page-1 load (`applyFilters`/`setSort`/`loadArticles(true)` via user action).
- This prevents the every-30s view wipe while keeping data fresh.

### Fix C — Backend watchdog (`backend/app.py` + `backend/progress.py`)

Each blog task `_run` (scan/fetch/like) can hang if a worker request wedges despite the timeout or the site API changes. Add a watchdog:
- In `backend/progress.py`, add a `watchdog(task_id, seconds)` helper — a daemon thread that sleeps `seconds`, then force-marks the task `done` with `{"error": "任务超时"}` IF the task isn't already done.
- In each blog `_run`, after `progress.store_progress(task_id, {..., "done": False})`, start `watchdog(task_id, 900)` (15 min). The main `_run` sets `done` on normal completion; the watchdog only fires if the main thread is still stuck.
- Guard: the watchdog checks `get_progress(task_id).get("done")` before overwriting, so a normally-completed task is never clobbered.

### Fix D — UTF-8 decode for content (`backend/blog.py`)

In `_fetch_one`, replace `resp.json()` with an explicit UTF-8 decode of the raw bytes:
```python
import json  # ensure imported at top of blog.py
data = json.loads(resp.content.decode("utf-8"))
```
This bypasses `charset_normalizer` entirely. (The scan path already sets `resp.encoding = resp.apparent_encoding or resp.encoding` for the HTML — that's a separate, correct fix from set B; content is JSON so raw-UTF-8 decode is right.)

## Files

- Modify: `frontend/blog.html` — Fix A (poll fallback) + Fix B (loadedAll-aware refresh).
- Modify: `frontend/index.html` — Fix A (poll fallback, same pattern).
- Modify: `backend/blog.py` — Fix D (UTF-8 decode).
- Modify: `backend/progress.py` — Fix C (`watchdog` helper).
- Modify: `backend/app.py` — Fix C (start watchdog in the 3 blog `_run`s).

## Verification

- Fix D: fetch an article with Chinese content → stored/displayed correctly (no Cyrillic garble). A unit check: `json.loads(resp.content.decode("utf-8"))` on a UTF-8 Chinese JSON body returns the correct string.
- Fix A: start a task, then evict/404 the task (or let it run > max) → poll stops, error toast shown, buttons re-enabled.
- Fix B: 加载全部 → wait 30s → view preserved (still shows all rows, not page 1).
- Fix C: hard to force a real hang; verify the watchdog thread starts, and that a normally-completed task is NOT overwritten (guard works). Optionally simulate by monkeypatching a worker to sleep past the watchdog.
- No test suite (per CLAUDE.md) — verify by running the app and exercising the UI.

## Non-goals

- No change to the scan/fetch/like retry logic or the 200-entry progress eviction.
- The watchdog timeout (15 min) and poll max (10 min) are heuristic; tuning later is fine.
- The checkin page gets only Fix A (poll fallback) — its auto-refresh (30s `refreshAll`) and per-account engine are out of scope for the blog-view-preservation change.
