# Design: Blog table — sorting, filtering, and content viewing

## Context

The like_bot → blog module integration (previous work on this branch) added a blog tools page (`frontend/blog.html`) with an articles table. The user wants three UX enhancements to that table, all frontend-focused with one small backend addition:

1. **Sorting** — clicking a column header (标题/作者/分类/点赞/更新时间/内容状态) sorts the table ascending/descending, cycling like Windows Explorer's detail view.
2. **Filtering** — filter controls restrict rows by 作者, 分类, 点赞 (min likes), and 内容状态.
3. **Viewing** — a "view" button per row shows the crawled article content as plain text in a browser modal; copying is allowed.

**User decisions (confirmed):**
- Sorting: click cycles asc/desc, client-side, applies to all columns.
- Filtering: client-side (instant, no server round-trip), on 作者/分类/点赞/内容状态.
- View content: new `GET /api/blog/article/<id>` endpoint returning the article's `content` field (the list payload intentionally excludes `content` to stay small).
- View UI: modal overlay showing plain-text content, copyable.

## Current state (verified)

- `frontend/blog.html` table columns: `☑ 标题 作者 分类 👍点赞 内容状态 更新时间`, rows rendered from `articles` array (`a.author`, `a.category`, `a.likes_count`, `a.content_fetched_at`, `a.created_at`, `a.url`, `a.title`, `a.id`).
- `content` is **excluded** from `/api/blog/articles` (deliberate — `store.list_articles` projects without `content`).
- `store.get_articles_by_ids(ids)` does `SELECT *` (includes `content`) but is **not** exposed via an API endpoint.
- Frontend already has: `API.get`/`API.post` helpers, `escapeHtml()`, toast, modal overlay CSS (`.modal-overlay`/`.modal`), `selectedIds` Set, `syncSelection()`, `updateActionButtons()`, 30s auto-refresh.

## Backend change

### New endpoint: `GET /api/blog/article/<id>`

In `backend/app.py`, add a single-article detail endpoint. It returns the article's full row (including `content`) for the "view content" modal.

```python
@app.route("/api/blog/article/<article_id>")
def blog_article_detail(article_id):
    """返回单篇文章详情（含 content，供博客页面查看）"""
    rows = store.get_articles_by_ids([article_id])
    if not rows:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(rows[0])
```

This reuses the existing `store.get_articles_by_ids` (`SELECT *`, includes `content`) — no store change needed. The list payload stays small; content is fetched on demand only when the user clicks "查看".

## Frontend change (`frontend/blog.html`)

### 1. Sorting

- Add a click handler on each sortable column header (`<th>`). Columns: 标题, 作者, 分类, 点赞, 更新时间, 内容状态.
- State: `sortState = { key: null, dir: null }` where `key` maps a column to an article field (`title`, `author`, `category`, `likes_count`, `content_fetched_at`, `contentFetched`), and `dir` is `"asc"` / `"desc"`.
- Clicking a header cycles: `无 → 升序(↑) → 降序(↓) → 无`.
- Sort the client-side `articles` array (a copy) before rendering. Use `localeCompare` for text (author, title, category) and numeric compare for likes/updated. Empty values sort last (or first for desc).
- Show an indicator in the header (▲/▼ or ↑/↓) for the active column.
- Sorting applies to the *currently displayed* rows (after filtering).

### 2. Filtering

- Add a filter bar above the table (a `.card` row with controls):
  - **作者** — a text input (live-filters as you type, `input` event) or a dropdown of unique authors. A text input is simplest and matches "filter by author"; a dropdown is cleaner for exact values. **Recommendation: dropdown of unique authors** (from the loaded articles) + a "全部" option.
  - **分类** — dropdown of unique categories + "全部".
  - **点赞 ≥** — a number input (min likes); articles with `likes_count` ≥ value pass.
  - **内容状态** — dropdown: 全部 / 已抓取 / 未抓取.
- State: `filters = { author: "", category: "", minLikes: null, contentFetched: null }`.
- Client-side: `applyFilters(articles)` returns the filtered array; empty filter = all.
- The article count (`共 N 篇`) should reflect the filtered count (e.g. `共 42 / 500 篇` or a separate "筛选后 N 篇").
- Filters compose with sorting (filter first, then sort).

### 3. Viewing content

- Add a "查看" button in each row's content-status column (or a new small action column). It's enabled only when `a.content_fetched_at` is truthy (content has been crawled). When not crawled, show "未抓取" with no button (or a disabled button).
- On click → `GET /api/blog/article/<id>` → show the `content` field in a modal.
- **Modal**: reuse the existing `.modal-overlay`/`.modal` styles (already in the page). The modal shows:
  - A title (the article's title).
  - The `content` rendered as **plain text** (in a `<pre>` or a scrollable `<div>` with `white-space: pre-wrap`), selectable/copyable.
  - A close button + click-outside-to-close (matching the checkin page's modal behavior).
- Since content is plain text, render it safely (escape HTML — do NOT inject as innerHTML; use `textContent` or escape). Copying is native (browser text selection + Ctrl+C).
- Handle the 404 / error case with a toast.

## Files

- Modify: `frontend/blog.html` — sorting, filtering, view button, content modal.
- Modify: `backend/app.py` — new `GET /api/blog/article/<id>` endpoint.
- No store change needed (reuses `get_articles_by_ids`).

## Verification

- `python run.py --no-browser`, then:
  - `curl -s http://127.0.0.1:5000/api/blog/article/<existing-id>` → returns the article row with `content`.
  - `curl -s http://127.0.0.1:5000/api/blog/article/nonexistent` → 404 `{"error": "文章不存在"}`.
  - `curl -s http://127.0.0.1:5000/blog` → page serves.
- Manual: click column headers to sort (asc/desc/clear); use filter controls; click "查看" on a crawled row to see content in the modal; confirm copying works.
- No test suite in the repo (per CLAUDE.md) — verification is by running the app and exercising the UI.

## Non-goals

- No change to the existing list payload size optimization (content stays out of `/api/blog/articles`).
- No server-side sort/filter (list is ≤500 rows; client-side is sufficient).
- No changes to the scan/fetch/like backend logic or the store schema.
