# Design: Blog page — 加载全部, tqdm progress bar, like fix + already-liked skip, clear-DB button

## Context

Four enhancements to the blog tools page (`frontend/blog.html`) plus backend support:

1. **加载全部 (Load All) button** — loads every article in the DB into the table (respecting the current filters/sort), no pagination. All other operations (scan/fetch/like, filters, sort, infinite scroll) are disabled until the load completes.
2. **tqdm-style progress bar** in the 任务进度 card, complementing the existing step animation.
3. **Like column fix** — display only the count of this bot's *successful local* likes (the `(2)` in "👍 0 (2)" → `👍 2`), and skip sending a like request for articles this account has already successfully liked.
4. **清空数据库 (Clear DB) button** — deletes all rows from `articles` + `likes`, with a confirm.

**User decisions (confirmed):**
- 加载全部: loads all rows, **respects current filters/sort**, all other ops disabled until done, cap ~10k rows.
- Progress bar: tqdm-style bar **complements** (keeps) the step animation.
- Like display: show only the count of successful local likes; skip already-liked articles.
- Clear-DB: a standalone button that wipes both tables, with confirm.

## Current state (verified)

- `frontend/blog.html`: 任务进度 card (`#progressCard`/`#progress`) shows only step animations via `renderProgressSteps(steps)`; like cell renders `👍 ${a.likes_count} (${likeHistory.length})`; action buttons `#scanBtn`/`#fetchBtn`/`#likeBtn`; `.table-wrap` infinite-scroll container; filter bar (作者/分类/点赞≥/内容状态) + sortable headers + `loadArticles(reset)`/`buildQuery()`.
- `backend/blog.py` `BlogEngine`: `scan_directory`/`fetch_contents`/`like_articles` each have a local `_progress(step, msg)` wrapper calling `progress_cb(step, msg)`; like POST is unconditional (`_like_one` → `POST /blog/{id}/like` → `store.record_like`).
- `backend/store.py`: `articles` + `likes` tables; `record_like`, `query_articles`, `get_likes_for_articles`, etc. No `has_liked` / `clear_all`.
- `backend/app.py` blog endpoints: each `_run` defines `def cb(step, msg): ... steps.append(...)`. `/api/blog/articles` paginates (`page_size` clamped 1..200).

## Backend changes

### 1. `backend/store.py`

Add:
```python
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


def clear_all() -> None:
    """清空文章与点赞记录"""
    conn = _conn()
    try:
        conn.execute("DELETE FROM likes")
        conn.execute("DELETE FROM articles")
        conn.commit()
    finally:
        conn.close()
```

### 2. `backend/blog.py` — already-liked skip + progress counts

- **`like_articles`**: in `_like_one`, before POSTing, check `store.has_liked(article_id, username)`. If already liked, return a "skip" marker without sending the request or recording a new row. Track a `skipped` count; result becomes `{total, success, failed, skipped}`.
- **Progress counts**: extend the local `_progress` wrappers to `_progress(step, msg, done=None, total=None)` in all three methods, threading `done`/`total` through to `progress_cb`. Values:
  - `fetch_contents`: `done = success + failed` (attempted), `total = len(article_ids)`.
  - `like_articles`: `total = len(article_ids)` (requested count), `done = success + failed` (attempted); skipped articles are counted separately in `skipped` and don't advance `done` — the bar shows attempted/total.
  - `scan_directory`: `done = total` (articles upserted so far), `total = None` (unknown → indeterminate bar).

### 3. `backend/app.py`

- Blog `_run` callbacks become `def cb(step, msg, done=None, total=None)`; store `data["done"]` and `data["total"]` into the progress dict so the frontend can render the bar.
- Add `GET /api/blog/articles/all` — same filters+sort as `/api/blog/articles` but returns ALL matching rows (no pagination): calls `store.query_articles(..., offset=0, limit=100000)` (cap ~10k+) and returns `{articles, likes, total}`.
- Add `POST /api/blog/clear` → `store.clear_all()`, returns `{"ok": True}`.

## Frontend changes (`frontend/blog.html`)

### 1. 加载全部 button

- Add a `加载全部` button in the filter bar area (`#loadAllBtn`, primary/ghost style). On click → disable all action/filter/sort buttons + suppress infinite scroll → `GET /api/blog/articles/all?<current buildQuery filters+sort>` → render all rows → re-enable.
- While loading, show a spinner on the button; "no other operations allowed" = scan/fetch/like buttons disabled + filter/sort inputs disabled + infinite-scroll suppressed (a `loadingAll` flag).
- After load-all, set `hasMore = false` (no infinite scroll), `totalArticles` from response, render.

### 2. tqdm-style progress bar

- Add `renderProgressBar(done, total)` → tqdm-style: fixed-width bar (e.g. 30 chars) of `█`/`░`, plus `NN%` when `total` known; when `total` is None (scan), show an indeterminate animated bar (or just a "已扫描 N 篇" line).
- In `pollProgress`, after rendering steps, render the bar from `p.done`/`p.total` into the progress card.

### 3. Like display + already-liked

- Display: `likeCell` shows `👍 ${successfulLocalLikes}` where `successfulLocalLikes = likeHistory.filter(l => l.success).length` (drop the site `likes_count` and the `(N)` sub-badge). Keep the tooltip with the history detail.
- Result summary (`renderSummary`) shows the `skipped` (已赞跳过) count when present.

### 4. 清空数据库 button

- Add a danger-styled `🗑 清空数据库` button (near the filter bar / actions). On click → `confirm("确定清空所有文章与点赞记录？此操作不可恢复")` → `POST /api/blog/clear` → reload (empty table). Disabled while a task runs.

## Files

- Modify: `backend/store.py` — `has_liked`, `clear_all`.
- Modify: `backend/blog.py` — already-liked skip in `like_articles`; `_progress(step, msg, done, total)` in all 3 methods.
- Modify: `backend/app.py` — cb signature + `done`/`total` in progress; `/api/blog/articles/all`; `POST /api/blog/clear`.
- Modify: `frontend/blog.html` — 加载全部 button, tqdm bar, like display fix, 清空 button.

## Verification

- `python run.py --no-browser`, then:
  - `curl -s "http://127.0.0.1:5000/api/blog/articles/all?author=X&sort=likes_count&order=desc"` → all matching rows (no `page`/`has_more`).
  - `curl -s -X POST "http://127.0.0.1:5000/api/blog/clear"` → `{"ok": true}`; `/api/blog/articles` now returns `total: 0`.
  - Like task progress polling shows `done`/`total`; already-liked articles skipped (result `skipped > 0`, no second POST).
- Manual: click 加载全部 (filters honored, buttons disabled during load); watch the tqdm bar during fetch/like; verify 👍 shows local success count; verify a second like on an already-liked article doesn't re-POST; click 清空数据库 (confirm) → table empties.
- No test suite (per CLAUDE.md) — verification by running the app and exercising the UI.

## Non-goals

- No change to `content`-exclusion in list payloads.
- No server-side persistence of the "loaded all" state — the button is a per-session UI action.
- Clear-DB deletes both articles AND likes (the whole blog DB); it is not scoped to a single account.
