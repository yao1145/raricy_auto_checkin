# Design: Blog table — sorting, filtering, and content viewing (server-side)

## Context

The like_bot → blog module integration (previous work on this branch) added a blog tools page (`frontend/blog.html`) with an articles table. The user wants three UX enhancements:

1. **Sorting** — clicking a column header (标题/作者/分类/点赞/更新时间/内容状态) sorts ascending/descending, cycling like Windows Explorer's detail view.
2. **Filtering** — filter controls restrict rows by 作者, 分类, 点赞 (min likes), and 内容状态.
3. **Viewing** — a "view" button per row shows the crawled article content as plain text in a browser modal; copying is allowed.

**Key constraint (user-stated):** the article list is ~5000 rows and growing, so **all filtering and sorting must be server-side** (SQL-backed), with **infinite scroll** pagination. No client-side filtering over a large array.

**User decisions (confirmed):**
- Sorting: click cycles asc/desc; **server-side** (SQL ORDER BY), applies to all sortable columns.
- Filtering: **server-side** on 作者/分类/点赞(≥)/内容状态; no free-text search box.
- Pagination: **infinite scroll** — the frontend fetches pages as the user scrolls near the bottom.
- View content: new `GET /api/blog/article/<id>` endpoint returning the article's `content` field (the list payload stays small).
- View UI: modal overlay showing plain-text content, copyable.

## Current state (verified)

- `frontend/blog.html` table columns: `☑ 标题 作者 分类 👍点赞 内容状态 更新时间`, rows rendered from an `articles` array.
- `content` is **excluded** from `/api/blog/articles` (deliberate — `store.list_articles` projects without `content`).
- `store.get_articles_by_ids(ids)` does `SELECT *` (includes `content`) but is not exposed via API.
- `store.list_articles(limit=500)` and `store.list_likes(limit=100)` are the existing queries.
- Frontend has: `API.get`/`API.post`, `escapeHtml()`, toast, `.modal-overlay`/`.modal` CSS, `selectedIds` Set, `syncSelection()`, `updateActionButtons()`, 30s auto-refresh.

## Backend changes

### 1. Store: add a query function with filters/sort/pagination

Add to `backend/store.py` (keep the existing `list_articles` — or refactor it to delegate):

```python
def query_articles(author=None, category=None, min_likes=None, status=None,
                   sort=None, order="asc", offset=0, limit=50) -> tuple[list[dict], int]:
    """分页查询文章。status: 'fetched' | 'unfetched' | None。返回 (rows, total)。"""
```

Build the WHERE clause from filters, ORDER BY from `sort`/`order`, then run a `SELECT ... COUNT(*)` for total + a `SELECT id, title, author, url, category, description, likes_count, content_fetched_at, created_at ...` for the page (still excluding `content`).

Sortable `sort` values: `title`, `author`, `category`, `likes_count`, `content_fetched_at` (更新时间 — falls back to `created_at` in SQL, e.g. `COALESCE(content_fetched_at, created_at)`), and `content_status` (sort by whether content_fetched_at is NULL).

Add:

```python
def list_distinct_authors() -> list[str]
def list_distinct_categories() -> list[str]
def get_likes_for_articles(article_ids: list[str]) -> list[dict]  # for per-page like tooltips
```

### 2. Endpoints in `backend/app.py`

Replace/extend `GET /api/blog/articles` to accept query params:

```
GET /api/blog/articles?author=..&category=..&min_likes=..&status=fetched|unfetched&sort=..&order=asc|desc&page=1&page_size=50
```

Returns:
```json
{ "articles": [...], "likes": [...], "total": 5000, "page": 1, "page_size": 50, "has_more": true }
```
- `likes` = `get_likes_for_articles(current page ids)` (per-page tooltips; not all likes).
- `total` = total matching rows (for the count display).

Add:
- `GET /api/blog/meta` → `{"authors": [...], "categories": [...]}` (distinct values, for the filter dropdowns).
- `GET /api/blog/article/<id>` → the article's full row (includes `content`) or 404.

## Frontend change (`frontend/blog.html`)

### 1. Filter bar (server-side)

Above the table, a `.card` filter row:
- 作者 dropdown (from `/api/blog/meta` authors + "全部").
- 分类 dropdown (from meta categories + "全部").
- 点赞 ≥ number input (min likes).
- 内容状态 dropdown: 全部 / 已抓取 / 未抓取.

On any filter change: reset to page 1, re-query `/api/blog/articles` with the params, replace the table body. Count display shows `共 {total} 篇` (server total).

### 2. Infinite scroll

- State: `page`, `hasMore`, `loadingMore`, plus the current filters/sort.
- Initial load fetches page 1. A scroll listener on the table-wrap (or window) detects when the user nears the bottom; when near bottom and `hasMore` and not `loadingMore`, fetch `page+1` and **append** rows.
- Each appended page's rows still render per-row (checkbox, view button, like tooltip).
- If a fetch errors mid-scroll, show a toast and allow retry on further scroll (don't hard-loop).

### 3. Sorting (server-side)

- Click a column header cycles `无 → 升序(↑) → 降序(↓) → 无`, with an indicator.
- On sort change: reset to page 1, re-query with `sort` + `order`, replace table.
- Sortable keys map to the backend `sort` values (title/author/category/likes_count/updated/content_status).

### 4. Viewing content

- A "查看" button in the 内容状态 column for crawled rows (`a.content_fetched_at` truthy); uncrawled rows show "未抓取" (no button / disabled).
- On click → `GET /api/blog/article/<id>` → modal (reuse `.modal-overlay`/`.modal`) showing the article title + `content` as escaped plain text in a scrollable `white-space: pre-wrap` container; selectable/copyable; close button + click-outside. 404 → toast.

### 5. Selection + auto-refresh

- `selectedIds` Set persists across pages (infinite scroll appends). `checkAll` selects the current page's rows only.
- 30s auto-refresh: re-query page 1 with current filters/sort and reset pagination (accept scroll reset — a minor UX trade-off for a tool page). During an active task (scan/fetch/like polling), keep auto-refresh but don't clobber the running task's UI.

## Files

- Modify: `backend/store.py` — add `query_articles`, `list_distinct_authors`, `list_distinct_categories`, `get_likes_for_articles`.
- Modify: `backend/app.py` — extend `/api/blog/articles`, add `/api/blog/meta` + `/api/blog/article/<id>`.
- Modify: `frontend/blog.html` — filter bar, infinite scroll, server-side sort, view button + modal.

## Verification

- `python run.py --no-browser`, then:
  - `curl "http://127.0.0.1:5000/api/blog/articles?page=1&page_size=50"` → `{articles, likes, total, has_more}`.
  - `curl "http://127.0.0.1:5000/api/blog/articles?author=X&sort=likes_count&order=desc"` → filtered+sorted page.
  - `curl "http://127.0.0.1:5000/api/blog/meta"` → `{authors, categories}`.
  - `curl -s "http://127.0.0.1:5000/api/blog/article/<id>"` → article with `content`; nonexistent → 404.
- Manual: filter → sort → scroll (infinite load) → click 查看 on a crawled row → modal shows content, copyable.
- No test suite (per CLAUDE.md) — verification by running the app and exercising the UI.

## Non-goals

- No free-text search box (user chose filters-only).
- `content` stays out of the list payload (view fetches it on demand).
- No changes to scan/fetch/like backend logic or the store schema (only new query functions).
- Selection is not persisted server-side; `selectedIds` resets on reload (unchanged from current behavior).
