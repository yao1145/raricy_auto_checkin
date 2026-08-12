# Blog Table Sort / Filter / View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add to the blog tools page (`frontend/blog.html`) three features — server-side column sorting, server-side filtering (作者/分类/点赞/内容状态), and on-demand article content viewing in a modal — backed by new SQL query + API endpoints.

**Architecture:** Extend `store.query_articles()` (SQL WHERE/ORDER BY/LIMIT + total count), expose paginated+filtered+sortable `/api/blog/articles` plus `/api/blog/meta` and `/api/blog/article/<id>`; the frontend re-queries on filter/sort change and infinite-scrolls by page.

**Tech Stack:** Python 3.10+, Flask, sqlite3 (stdlib), vanilla HTML/JS.

## Global Constraints

- List is ~5000 rows → **server-side** filter + sort + pagination. No client-side filtering over a large array.
- `content` stays OUT of `/api/blog/articles` (list payload stays small); view fetches it on demand via `/api/blog/article/<id>`.
- Pure `requests`/sqlite only — no new deps beyond what's installed. No Selenium.
- SQL param binding everywhere (never interpolate user input into SQL values).
- Sortable columns map to: `title`, `author`, `category`, `likes_count`, `content_fetched_at` (更新时间, with `COALESCE(content_fetched_at, created_at)` fallback), `content_status` (by whether content_fetched_at is NULL).
- Filters: `author` (exact), `category` (exact), `min_likes` (≥), `status` (`fetched`/`unfetched`/None).
- Pagination: `page` (1-based) + `page_size` (default 50); response `{articles, likes, total, page, page_size, has_more}`.
- Infinite scroll on the frontend; `selectedIds` Set persists across pages; `checkAll` selects the current page's rows.
- Comment style: Chinese/English mix matching `backend/store.py`.
- No real local paths in committed files; `runtime/` gitignored.

---

### Task 1: Store query functions

**Files:**
- Modify: `backend/store.py`

**Interfaces:**
- Produces:
  - `store.query_articles(author=None, category=None, min_likes=None, status=None, sort=None, order="asc", offset=0, limit=50) -> tuple[list[dict], int]`
  - `store.list_distinct_authors() -> list[str]`
  - `store.list_distinct_categories() -> list[str]`
  - `store.get_likes_for_articles(article_ids: list[str]) -> list[dict]`

- [ ] **Step 1: Add `query_articles`**

Append to `backend/store.py`:

```python
SORT_COLUMNS = {
    "title": "title",
    "author": "author",
    "category": "category",
    "likes_count": "likes_count",
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
        where.append("likes_count >= ?")
        params.append(min_likes)
    if status == "fetched":
        where.append("content_fetched_at IS NOT NULL")
    elif status == "unfetched":
        where.append("content_fetched_at IS NULL")

    order_by = "created_at DESC"
    if sort in SORT_COLUMNS:
        col = SORT_COLUMNS[sort]
        direction = "ASC" if order == "asc" else "DESC"
        if sort == "content_status":
            order_by = f"(content_fetched_at IS NULL) {direction}, created_at {direction}"
        else:
            order_by = f"{col} {direction}, created_at {direction}"

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    conn = _conn()
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM articles{where_sql}", params)
        total = cur.fetchone()[0]
        cur = conn.execute(
            f"""SELECT id, title, author, url, category, description,
                       likes_count, content_fetched_at, created_at
                FROM articles{where_sql} ORDER BY {order_by} LIMIT ? OFFSET ?""",
            params + [limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows, total
    finally:
        conn.close()
```

Note: the `f`-strings interpolate `where_sql`/`order_by` which are built from a fixed allowlist (`SORT_COLUMNS` / hardcoded strings) — never from user input. `params` are always bound.

- [ ] **Step 2: Add distinct + per-page likes helpers**

```python
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
```

- [ ] **Step 3: Verify**

```bash
python -c "
import sys; sys.path.insert(0,'.')
from backend import store
store.init_db()
# insert a couple rows if empty
conn = __import__('sqlite3').connect(store.get_db_path())
conn.execute(\"INSERT OR REPLACE INTO articles (id,title,author,url,category,description,likes_count) VALUES ('t1','One','Alice','http://x/1','news','d',5)\")
conn.execute(\"INSERT OR REPLACE INTO articles (id,title,author,url,category,description,likes_count,content_fetched_at) VALUES ('t2','Two','Bob','http://x/2','tech','d',3,'2026-08-12')\")
conn.commit(); conn.close()
print('authors', store.list_distinct_authors())
print('cats', store.list_distinct_categories())
rows, total = store.query_articles(sort='likes_count', order='desc', limit=10)
print('total', total, 'first', rows[0]['id'] if rows else None)
rows, total = store.query_articles(status='fetched')
print('fetched total', total, [r['id'] for r in rows])
"
```
Expected: `authors ['Alice','Bob']`, `cats ['news','tech']`, `total 2`, `first t1`, `fetched total 1 ['t2']`.

- [ ] **Step 4: Commit**

```bash
git add backend/store.py
git commit -m "feat: add server-side blog article query with filters/sort/pagination"
```

---

### Task 2: Blog API endpoints

**Files:**
- Modify: `backend/app.py`

**Interfaces:**
- Consumes: `store.query_articles`, `store.list_distinct_authors`, `store.list_distinct_categories`, `store.get_likes_for_articles`, `store.get_articles_by_ids`.
- Produces:
  - `GET /api/blog/articles?author=&category=&min_likes=&status=&sort=&order=&page=&page_size=` → `{articles, likes, total, page, page_size, has_more}`
  - `GET /api/blog/meta` → `{authors, categories}`
  - `GET /api/blog/article/<article_id>` → article row (with `content`) or `{"error": ...}` 404

- [ ] **Step 1: Rewrite `GET /api/blog/articles`**

Replace the existing `blog_articles()` (app.py:260-263):

```python
@app.route("/api/blog/articles")
def blog_articles():
    """分页 + 服务端筛选 + 排序的文章列表"""
    args = request.args
    author = args.get("author", "").strip() or None
    category = args.get("category", "").strip() or None
    min_likes = args.get("min_likes", type=int)
    status = args.get("status", "").strip() or None
    if status not in (None, "fetched", "unfetched"):
        status = None
    sort = args.get("sort", "").strip() or None
    order = args.get("order", "asc").strip().lower()
    if order not in ("asc", "desc"):
        order = "asc"
    page = max(1, args.get("page", 1, type=int))
    page_size = min(200, max(1, args.get("page_size", 50, type=int)))

    offset = (page - 1) * page_size
    rows, total = store.query_articles(
        author=author, category=category, min_likes=min_likes, status=status,
        sort=sort, order=order, offset=offset, limit=page_size,
    )
    likes = store.get_likes_for_articles([r["id"] for r in rows])
    has_more = offset + len(rows) < total
    return jsonify({
        "articles": rows, "likes": likes, "total": total,
        "page": page, "page_size": page_size, "has_more": has_more,
    })
```

- [ ] **Step 2: Add `/api/blog/meta` and `/api/blog/article/<id>`**

```python
@app.route("/api/blog/meta")
def blog_meta():
    """作者/分类下拉选项"""
    return jsonify({
        "authors": store.list_distinct_authors(),
        "categories": store.list_distinct_categories(),
    })


@app.route("/api/blog/article/<article_id>")
def blog_article_detail(article_id):
    """单篇详情（含 content，供查看弹窗）"""
    rows = store.get_articles_by_ids([article_id])
    if not rows:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(rows[0])
```

- [ ] **Step 3: Verify routes + queries**

```bash
python -c "
import sys; sys.path.insert(0,'.')
from backend.app import app
print(sorted(str(r) for r in app.url_map.iter_rules() if 'blog' in str(r)))
"
python -c "
import sys; sys.path.insert(0,'.')
from backend.app import app
c = app.test_client()
r = c.get('/api/blog/articles?page=1&page_size=50')
print('status', r.status_code, 'keys', sorted(r.get_json().keys()))
r2 = c.get('/api/blog/meta'); print('meta', r2.status_code, sorted(r2.get_json().keys()))
r3 = c.get('/api/blog/article/nonexistent'); print('404?', r3.status_code)
"
```
Expected: routes include `/api/blog/article/<article_id>`, `/api/blog/meta`, `/api/blog/articles`; articles keys `['articles','has_more','likes','page','page_size','total']`; meta keys `['authors','categories']`; 404 for nonexistent.

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "feat: add paginated blog articles API with filters/sort + meta/detail endpoints"
```

---

### Task 3: Frontend — filters, sorting, infinite scroll, view modal

**Files:**
- Modify: `frontend/blog.html`

**Interfaces:**
- Consumes: `/api/blog/articles` (query params), `/api/blog/meta`, `/api/blog/article/<id>`.

- [ ] **Step 1: Add the filter bar + table header sort**

After the `<div class="section-header">` (line 301-304), insert a filter row card:

```html
<div class="card" style="padding:12px 16px;">
  <div class="form-row" style="flex-wrap:wrap;align-items:flex-end;gap:10px;">
    <div class="form-group" style="flex:1;min-width:140px;">
      <label>作者</label>
      <select id="filterAuthor"><option value="">全部</option></select>
    </div>
    <div class="form-group" style="flex:1;min-width:140px;">
      <label>分类</label>
      <select id="filterCategory"><option value="">全部</option></select>
    </div>
    <div class="form-group" style="flex:1;min-width:120px;">
      <label>点赞 ≥</label>
      <input type="number" id="filterMinLikes" min="0" value="">
    </div>
    <div class="form-group" style="flex:1;min-width:140px;">
      <label>内容状态</label>
      <select id="filterStatus">
        <option value="">全部</option>
        <option value="fetched">已抓取</option>
        <option value="unfetched">未抓取</option>
      </select>
    </div>
  </div>
</div>
```

Make the `<th>` elements clickable sortable headers. Change the header `<tr>` to add `onclick="setSort('title')"` etc., plus a `data-sort` attribute and a sort indicator `<span class="sort-ind"></span>`. Columns → keys: 标题→`title`, 作者→`author`, 分类→`category`, 点赞→`likes_count`, 内容状态→`content_status`, 更新时间→`content_fetched_at`. The checkbox column is not sortable.

- [ ] **Step 2: Add state + query-builder + load/paginate functions**

Add near the existing `loadArticles`:

```javascript
// ── 筛选 / 排序 / 分页状态 ───────────────────────────────
let filters = { author: "", category: "", minLikes: null, status: "" };
let sortState = { key: null, dir: "asc" };
let currentPage = 1;
let hasMore = false;
let loadingMore = false;
let totalArticles = 0;
let articles = [];
let likes = [];

function buildQuery() {
  const p = new URLSearchParams();
  if (filters.author) p.set("author", filters.author);
  if (filters.category) p.set("category", filters.category);
  if (filters.minLikes != null && filters.minLikes !== "") p.set("min_likes", filters.minLikes);
  if (filters.status) p.set("status", filters.status);
  if (sortState.key) { p.set("sort", sortState.key); p.set("order", sortState.dir); }
  p.set("page", currentPage);
  p.set("page_size", 50);
  return p.toString();
}

async function loadArticles(reset = true) {
  if (loadingMore) return;
  if (reset) { currentPage = 1; articles = []; }
  try {
    const data = await API.get(`/api/blog/articles?${buildQuery()}`);
    if (reset) { articles = data.articles; likes = data.likes; }
    else { articles = articles.concat(data.articles); likes = likes.concat(data.likes); }
    totalArticles = data.total;
    hasMore = data.has_more;
    currentPage = data.page;
    renderArticlesTable();
  } catch (e) {
    toast("加载文章失败: " + e.message, "error");
  } finally {
    loadingMore = false;
  }
}

function applyFilters() {
  filters = {
    author: document.getElementById("filterAuthor").value,
    category: document.getElementById("filterCategory").value,
    minLikes: document.getElementById("filterMinLikes").value,
    status: document.getElementById("filterStatus").value,
  };
  loadArticles(true);
}

function setSort(key) {
  if (sortState.key === key) {
    sortState.dir = sortState.dir === "asc" ? "desc" : sortState.dir === "desc" ? null : "asc";
    if (sortState.dir === null) sortState.key = null;
  } else {
    sortState.key = key;
    sortState.dir = "asc";
  }
  updateSortIndicators();
  loadArticles(true);
}
```

Wire the filter controls to `applyFilters()` via `onchange`/`oninput`. Add infinite-scroll: a scroll listener on the table container that, when near the bottom, `loadingMore` false and `hasMore` true, increments `currentPage` and calls `loadArticles(false)`.

- [ ] **Step 3: Update `renderArticlesTable`**

Keep the existing row rendering (checkbox, title link, author, category badge, like tooltip, content badge, updated). Changes:
- Use `articles` (which may now be a concatenated set across pages — render all currently-loaded).
- `document.getElementById("articleCount").textContent = \`共 ${totalArticles} 篇\`;` (server total, not `articles.length`).
- The 内容状态 column: if `a.content_fetched_at` truthy, show the green badge **plus** a small "查看" button (`<button class="btn btn-ghost btn-sm" onclick="viewContent('${escapeHtml(a.id)}', '${escapeHtml(a.title)}')">查看</button>`); else the "未抓取" badge (no button).
- Keep `selectedIds` for checkboxes; `checkAll` selects the current page's rows only.
- `updateSortIndicators()` sets `▲`/`▼` on the active header and clears others.

- [ ] **Step 4: Add the view-content modal + `viewContent()`**

Add a modal (mirroring the checkin page's `.modal-overlay`/`.modal` pattern) after the table card:

```html
<div class="modal-overlay" id="contentModal">
  <div class="modal">
    <button class="modal-close" onclick="closeContentModal()">&times;</button>
    <h2 id="contentModalTitle">文章内容</h2>
    <div id="contentModalBody" style="white-space:pre-wrap;font-size:13px;line-height:1.7;max-height:60vh;overflow-y:auto;user-select:text;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:14px;"></div>
    <div class="btn-row" style="justify-content:flex-end;margin-top:12px;">
      <button class="btn btn-ghost btn-sm" onclick="closeContentModal()">关闭</button>
    </div>
  </div>
</div>
```

Add JS:

```javascript
async function viewContent(id, title) {
  document.getElementById("contentModalTitle").textContent = title || "文章内容";
  const body = document.getElementById("contentModalBody");
  body.textContent = "加载中...";
  document.getElementById("contentModal").classList.add("open");
  try {
    const article = await API.get(`/api/blog/article/${encodeURIComponent(id)}`);
    body.textContent = article.content || "(无内容)";
  } catch (e) {
    body.textContent = "";
    toast("加载内容失败: " + e.message, "error");
    closeContentModal();
  }
}
function closeContentModal() {
  document.getElementById("contentModal").classList.remove("open");
}
// click-outside to close
document.getElementById("contentModal").addEventListener("click", function(e) {
  if (e.target === this) closeContentModal();
});
```

Use `textContent` (NOT innerHTML) so content renders as plain escaped text — this is the "plain text, copyable" requirement. Copying is native (select + Ctrl+C).

- [ ] **Step 5: Update `updateActionButtons` / load meta + init**

- On init, `loadMeta()` fetches `/api/blog/meta` and populates the 作者/分类 dropdowns.
- `refreshAll()` (or the init path) calls `loadMeta()` + `loadArticles(true)` + `loadAccounts()`.
- The 30s auto-refresh calls `loadArticles(true)` (server re-query, resets pagination) — but skip while a task is polling (guard on the existing task-state flag if present).
- Keep `updateActionButtons()` unchanged (it keys off `selectedIds`).

- [ ] **Step 6: Verify**

Run the server and exercise:
```bash
python run.py --no-browser &
# then curl:
curl -s "http://127.0.0.1:5000/api/blog/articles?sort=likes_count&order=desc&page=1&page_size=10"
curl -s "http://127.0.0.1:5000/api/blog/meta"
curl -s "http://127.0.0.1:5000/api/blog/article/t2"   # existing id → has content
curl -s "http://127.0.0.1:5000/blog"                  # page serves
```
Manual: filter by author → count changes; sort asc/desc; scroll to load more; click 查看 on a fetched row → modal with copyable plain text.

- [ ] **Step 7: Commit**

```bash
git add frontend/blog.html
git commit -m "feat: add sort/filter/infinite-scroll/view-content to blog page"
```

---

## Self-Review Notes

- **Spec coverage:** backend query (T1) → endpoints (T2) → frontend (T3). All three features + the on-demand content view covered.
- **Type consistency:** `query_articles` returns `(rows, total)` consumed by `/api/blog/articles`; `store.get_likes_for_articles` feeds `likes`; `list_distinct_authors/categories` feed `/api/blog/meta`; `viewContent` uses `/api/blog/article/<id>` → `store.get_articles_by_ids`. Consistent across tasks.
- **Placeholder scan:** no TBD/TODO; every step has concrete code.
