# Blog Load-All / Progress Bar / Like Fix / Clear-DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four features to the blog tools page: a 加载全部 (load-all) button, a tqdm-style progress bar, a like-count fix + already-liked skip, and a 清空数据库 (clear-DB) button.

**Architecture:** Backend adds `store.has_liked`/`store.clear_all`, threads `done`/`total` counts through the blog progress callbacks, and adds `/api/blog/articles/all` + `POST /api/blog/clear`. Frontend adds the two buttons, renders the tqdm bar, and fixes the like cell.

**Tech Stack:** Python 3.10+, Flask, sqlite3 (stdlib), vanilla HTML/JS.

## Global Constraints

- `content` stays OUT of list payloads (view fetches on demand).
- 加载全部 respects current filters/sort, caps ~10k rows, disables all other ops until done.
- Progress bar complements (keeps) the step animation.
- Like column shows only the successful-local-like count; already-liked articles are skipped (no second POST).
- 清空数据库 deletes both `articles` and `likes` with a confirm.
- SQL param binding everywhere.
- Comment style: Chinese/English mix matching backend/store.py.
- Vanilla JS, consistent dark-theme style, Chinese labels.
- No real local paths in committed files; `runtime/` gitignored.

---

### Task 1: Store helpers

**Files:**
- Modify: `backend/store.py`

**Interfaces:**
- Produces:
  - `store.has_liked(article_id: str, account: str) -> bool`
  - `store.clear_all() -> None`

- [ ] **Step 1: Add `has_liked` + `clear_all`**

Append to `backend/store.py`:

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

- [ ] **Step 2: Verify**

```bash
python -c "
import sys; sys.path.insert(0,'.')
from backend import store
store.init_db()
store.record_like('t1', 'alice', True, 'ok')
store.record_like('t1', 'bob', False, 'fail')
print('alice has_liked t1:', store.has_liked('t1', 'alice'))   # True
print('bob has_liked t1:', store.has_liked('t1', 'bob'))       # False (fail row ignored)
n_before = len(store.list_articles(500))
store.clear_all()
print('articles after clear:', len(store.list_articles(500)))  # 0
"
```
Expected: `alice has_liked t1: True`, `bob has_liked t1: False`, `articles after clear: 0`.

- [ ] **Step 3: Commit**

```bash
git add backend/store.py
git commit -m "feat: add has_liked and clear_all store helpers"
```

---

### Task 2: BlogEngine progress counts + already-liked skip

**Files:**
- Modify: `backend/blog.py`

**Interfaces:**
- Consumes: `store.has_liked`.
- Produces:
  - `BlogEngine._progress(step, msg, done=None, total=None)` in `scan_directory`/`fetch_contents`/`like_articles` — passes `done`/`total` to `progress_cb`.
  - `like_articles` returns `{total, success, failed, skipped}` and skips already-liked articles.

- [ ] **Step 1: Extend `_progress` in all three methods**

In each of `scan_directory`, `fetch_contents`, `like_articles`, change the local `_progress` wrapper:

```python
def _progress(step, msg, done=None, total=None):
    if progress_cb:
        try:
            progress_cb(step, msg, done=done, total=total)
        except Exception:
            pass
```

Update the `_progress(...)` call sites:
- **scan_directory**: after each page upsert, `_progress("scan", f"第 {page} 页，已收录 {total} 篇", done=total, total=None)` (indeterminate).
- **fetch_contents**: after each round, `_progress("fetch", f"已抓取 {success} 篇，待重试 {len(pending)}", done=success + failed, total=total)`.
- **like_articles**: after each round, `_progress("like", f"已点赞 {success} 篇，待重试 {len(pending)}", done=success + failed, total=total)`.

(Note: `total` in the enclosing scope shadows the param name — rename the enclosing locals if needed, e.g. use `requested_total` inside the methods, OR keep the param and the loop var distinct. Whichever is cleaner; just ensure no shadowing bug.)

- [ ] **Step 2: Add already-liked skip in `like_articles`**

In `_like_one`, before the POST:

```python
def _like_one(article_id):
    if store.has_liked(article_id, username):
        return "skipped", article_id, False
    ...
```

Change the return contract so skipped is distinguishable. In the collector:

```python
for fut in as_completed(futs):
    status, aid, retryable = fut.result()
    if status == "skipped":
        skipped += 1
    elif status is True:
        success += 1
    elif retryable:
        retry.append(aid)
    else:
        failed += 1
```

Initialize `skipped = 0`; return `{"total": total, "success": success, "failed": failed, "skipped": skipped}`. The `_progress("done", ...)` message can mention skipped: `f"点赞完成：成功 {success}，失败 {failed}，跳过 {skipped}"`.

- [ ] **Step 3: Verify**

```bash
python -c "from backend.blog import BlogEngine; print('ok')"
python -c "import backend.app; print('app-ok')"
```
Expected: both import cleanly. (The already-liked skip path needs `store.has_liked` which returns True for a recorded successful like — a quick unit-level check: insert a like, then confirm `_like_one` on the same (article, account) returns the skip marker.)

- [ ] **Step 4: Commit**

```bash
git add backend/blog.py
git commit -m "feat: progress counts and already-liked skip in BlogEngine"
```

---

### Task 3: Blog API endpoints (all + clear + progress counts)

**Files:**
- Modify: `backend/app.py`

**Interfaces:**
- Consumes: `store.query_articles`, `store.get_likes_for_articles`, `store.clear_all`.
- Produces:
  - `GET /api/blog/articles/all?<filters+sort>` → `{articles, likes, total}` (no pagination).
  - `POST /api/blog/clear` → `{"ok": true}`.
  - Blog task progress dicts now include `done`/`total`.

- [ ] **Step 1: Update the three `_run` cb closures**

In `blog_scan`, `blog_fetch`, `blog_like`, change `def cb(step, msg):` to:

```python
def cb(step, msg, done=None, total=None):
    data = progress.get_progress(task_id) or {}
    data["current_step"] = step
    data["steps"].append({"step": step, "message": msg, "time": datetime.now().strftime("%H:%M:%S")})
    if done is not None:
        data["done_count"] = done
    if total is not None:
        data["total_count"] = total
    progress.store_progress(task_id, data)
```

- [ ] **Step 2: Add `/api/blog/articles/all` and `POST /api/blog/clear`**

After `blog_articles()`:

```python
@app.route("/api/blog/articles/all")
def blog_articles_all():
    """加载全部文章（同一筛选/排序，无分页；约 1 万条上限）"""
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
    rows, total = store.query_articles(
        author=author, category=category, min_likes=min_likes, status=status,
        sort=sort, order=order, offset=0, limit=100000,
    )
    likes = store.get_likes_for_articles([r["id"] for r in rows])
    return jsonify({"articles": rows, "likes": likes, "total": total})


@app.route("/api/blog/clear", methods=["POST"])
def blog_clear():
    """清空文章与点赞记录"""
    store.clear_all()
    return jsonify({"ok": True})
```

(Note: `query_articles` with `limit=100000` and `offset=0` returns all rows; the response has no `page`/`has_more`.)

- [ ] **Step 3: Verify routes + responses**

```bash
python -c "
import sys; sys.path.insert(0,'.')
from backend.app import app
c = app.test_client()
print(sorted(str(r) for r in app.url_map.iter_rules() if 'blog' in str(r)))
r = c.get('/api/blog/articles/all?sort=likes_count&order=desc')
print('all keys', sorted(r.get_json().keys()))
r2 = c.post('/api/blog/clear'); print('clear', r2.status_code, r2.get_json())
r3 = c.get('/api/blog/articles'); print('after clear total', r3.get_json()['total'])
"
```
Expected: routes include `/api/blog/articles/all` and `/api/blog/clear`; all keys `['articles','likes','total']`; clear 200 `{'ok': true}`; after-clear total 0.

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "feat: blog articles-all and clear endpoints, progress counts"
```

---

### Task 4: Frontend — 加载全部, tqdm bar, like fix, 清空 button

**Files:**
- Modify: `frontend/blog.html`

**Interfaces:**
- Consumes: `/api/blog/articles/all`, `/api/blog/clear`, and the progress dict's `done_count`/`total_count`.

- [ ] **Step 1: Add 加载全部 + 清空 buttons**

In the filter bar card (near the 作者/分类 dropdowns), add a button row:

```html
<div class="btn-row" style="justify-content:flex-start;margin-top:12px;flex-wrap:wrap;gap:8px;">
  <button class="btn btn-primary" id="loadAllBtn" onclick="loadAll()">📥 加载全部</button>
  <button class="btn btn-danger" id="clearBtn" onclick="clearDb()" style="margin-left:auto;">🗑 清空数据库</button>
</div>
```

Wire `#clearBtn` to `clearDb()` (confirm + `POST /api/blog/clear` + reload).

- [ ] **Step 2: Add `loadAll()` + `loadingAll` flag**

```javascript
let loadingAll = false;

async function loadAll() {
  if (loadingAll || _running) return;
  loadingAll = true;
  setControlsDisabled(true);   // disable scan/fetch/like + filter/sort inputs + suppress scroll
  const btn = document.getElementById("loadAllBtn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 加载中...';
  try {
    const q = buildQuery();  // buildQuery already includes filters+sort (page/page_size ignored by /all)
    const data = await API.get(`/api/blog/articles/all?${q}`);
    articles = data.articles; likes = data.likes; totalArticles = data.total;
    hasMore = false;  // no infinite scroll after load-all
    renderArticlesTable();
    toast(`已加载全部 ${totalArticles} 篇`);
  } catch (e) {
    toast("加载全部失败: " + e.message, "error");
  } finally {
    loadingAll = false;
    setControlsDisabled(false);
    btn.disabled = false;
    btn.innerHTML = "📥 加载全部";
  }
}
```

`setControlsDisabled(disabled)` — disable/enable `#scanBtn`, `#fetchBtn`, `#likeBtn`, the filter `<select>`/`<input>`, and the sort headers (add a `.sorting-disabled` class that ignores clicks). The infinite-scroll scroll listener must also check `loadingAll` and no-op.

- [ ] **Step 3: Add the tqdm progress bar**

Add `renderProgressBar(done, total)`:

```javascript
function renderProgressBar(done, total) {
  const width = 30; // 字符宽度，tqdm 风格
  if (done == null) return "";
  let pct = "", barStr;
  if (total) {
    const p = Math.min(1, done / total);
    const filled = Math.round(p * width);
    barStr = "█".repeat(filled) + "░".repeat(width - filled);
    pct = ` ${(p * 100).toFixed(0)}%`;
  } else {
    // 未知总数（扫描）：不确定性进度条
    const frame = (Math.floor(Date.now() / 400) % (width - 4));
    barStr = "░".repeat(frame) + "██" + "░".repeat(width - frame - 2);
    pct = ` ${done} 篇`;
  }
  return `<div style="font-family:monospace;font-size:12px;margin:8px 0;white-space:pre;">[${barStr}]${pct}</div>`;
}
```

In `pollProgress`, after rendering steps, render the bar from `p.done_count`/`p.total_count`:

```javascript
const bar = renderProgressBar(p.done_count, p.total_count);
progressDiv.innerHTML = renderProgressSteps(p.steps || []) + bar;
```

(The `frame` uses `Date.now()` — fine in the browser; the tqdm-style animated indeterminate bar advances via the 500ms poll.)

- [ ] **Step 4: Fix the like column**

Replace the like-cell logic (currently shows `👍 ${a.likes_count} (${likeHistory.length})`):

```javascript
const likeHistory = likesByArticle[id] || [];
const successLikes = likeHistory.filter(l => l.success).length;
const likeCell = successLikes > 0
  ? `<span title="${escapeHtml(likeHistory.map(l => `${l.success ? "✅" : "❌"} ${l.account} ${l.liked_at || ""}`).join("\n"))}" style="cursor:help;">👍 ${successLikes}</span>`
  : "—";
```

Show only the successful-local-like count. The tooltip keeps the full history. Drop `a.likes_count` from the cell (the site's own count is not the bot's history).

Also update `renderSummary` to show the `skipped` count when present:
```javascript
if ("success" in results) {
  const skip = results.skipped ? `，跳过 <b>${results.skipped}</b>` : "";
  return `<div style="margin:3px 0;">✅ 成功 <b style="color:var(--green);">${results.success}</b> / 共 ${results.total} 篇，失败 <b style="color:var(--red);">${results.failed}</b>${skip}</div>`;
}
```

- [ ] **Step 5: Add `clearDb()`**

```javascript
async function clearDb() {
  if (_running || loadingAll) { toast("请先等待当前任务完成", "error"); return; }
  if (!confirm("确定清空所有文章与点赞记录？此操作不可恢复。")) return;
  try {
    await API.post("/api/blog/clear", {});
    toast("数据库已清空");
    articles = []; likes = []; totalArticles = 0; hasMore = false;
    renderArticlesTable();
  } catch (e) {
    toast("清空失败: " + e.message, "error");
  }
}
```

- [ ] **Step 6: Verify**

```bash
python run.py --no-browser &
# then:
curl -s "http://127.0.0.1:5000/api/blog/articles/all?sort=likes_count&order=desc" | python -c "import sys,json; d=json.load(sys.stdin); print('total', d['total'])"
curl -s -X POST "http://127.0.0.1:5000/api/blog/clear"   # {"ok": true}
curl -s "http://127.0.0.1:5000/api/blog/articles" | python -c "import sys,json; print(json.load(sys.stdin)['total'])"  # 0
curl -s "http://127.0.0.1:5000/blog" | head -5           # serves
```
Manual: 加载全部 (filters honored, buttons disabled during load, no infinite scroll after); progress bar shows during fetch/like (with % once done/total known); 👍 shows local success count; a second like on an already-liked article skips (no re-POST, `skipped` in summary); 清空数据库 wipes the table.

- [ ] **Step 7: Commit**

```bash
git add frontend/blog.html
git commit -m "feat: load-all button, tqdm progress bar, like-count fix, clear-DB button"
```

---

## Self-Review Notes

- **Spec coverage:** store helpers (T1) → BlogEngine progress+skip (T2) → endpoints (T3) → frontend (T4). All four features covered.
- **Type consistency:** `store.has_liked`/`clear_all` consumed by T2/T3; `_progress(step,msg,done,total)` → `cb(step,msg,done,total)` → `data["done_count"]`/`data["total_count"]` consumed by the frontend bar; `like_articles` returns `{total,success,failed,skipped}`. Consistent.
- **Placeholder scan:** no TBD/TODO; every step has concrete code.
