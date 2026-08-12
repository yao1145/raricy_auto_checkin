# Blog/checkin Bug-Fix Implementation Plan (poll / refresh / garbled)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two bugs — (1) garbled scraped content from a charset mis-guess, and (2) auto-refresh resetting the view + progress polls hanging forever. Four fixes: poll terminal fallback (A), refresh-preserves-view (B), backend watchdog (C), UTF-8 decode (D).

**Architecture:** Frontend adds a bounded poll (`POLL_MAX_MS` + stop-on-404) and a `loadedAll` flag so the 30s refresh preserves the view; backend adds a `watchdog` daemon in `progress.py` that force-flips a stuck task's `done`, and `_fetch_one` decodes JSON as explicit UTF-8.

**Tech Stack:** Python 3.10+, Flask, requests, vanilla HTML/JS.

## Global Constraints

- Fix A applies to BOTH `frontend/blog.html` and `frontend/index.html` (checkin page's inline poll).
- Fix B applies to `frontend/blog.html` only.
- Fix C applies to `backend/progress.py` + `backend/app.py` (the 3 blog `_run`s: scan/fetch/like).
- Fix D applies to `backend/blog.py` `_fetch_one`.
- The watchdog must NOT clobber a normally-completed task (guard on `done`).
- The poll must ALWAYS terminate (max duration + stop on 404), never freeze the UI.
- Comment style: Chinese/English mix matching each file.
- No test suite (per CLAUDE.md) — verify by running the app / unit checks.
- No real local paths in committed files; `runtime/` gitignored.

---

### Task 1: Fix D — UTF-8 decode for content (`backend/blog.py`)

**Files:**
- Modify: `backend/blog.py`

**Interfaces:**
- Produces: `_fetch_one` decodes the JSON body as explicit UTF-8.

- [ ] **Step 1: Add `import json` and change `_fetch_one` decode**

Add `import json` at the top of `backend/blog.py` (after `import re`). In `_fetch_one` (around blog.py:167-171), replace `data = resp.json()` with:

```python
data = json.loads(resp.content.decode("utf-8"))
```

The surrounding logic (`content = data.get("meta", {}).get("content", "")`) stays unchanged.

- [ ] **Step 2: Verify**

```bash
python -c "
import json
raw = json.dumps({'meta': {'content': '游戏『水仙』文本（KFC汉化版）'}}, ensure_ascii=False).encode('utf-8')
data = json.loads(raw.decode('utf-8'))
assert data['meta']['content'] == '游戏『水仙』文本（KFC汉化版）'
print('utf8 decode ok')
"
python -c "from backend.blog import BlogEngine; print('ok')"
```
Expected: both print ok. (The `\uXXXX` ensure_ascii=False path is what the site sends for Chinese.)

- [ ] **Step 3: Commit**

```bash
git add backend/blog.py
git commit -m "fix: decode blog content JSON as explicit UTF-8"
```

---

### Task 2: Fix C — backend watchdog (`backend/progress.py` + `backend/app.py`)

**Files:**
- Modify: `backend/progress.py`
- Modify: `backend/app.py`

**Interfaces:**
- Produces: `progress.watchdog(task_id: str, seconds: int) -> None` — starts a daemon thread that force-marks the task done-with-error if it's still running after `seconds`.
- Consumes: called at the start of each blog `_run` (scan/fetch/like).

- [ ] **Step 1: Add `watchdog` to `backend/progress.py`**

```python
import threading
import time


def watchdog(task_id: str, seconds: int) -> None:
    """看门狗：若任务在 seconds 秒后仍未完成，强制标记为超时失败。
    仅在任务尚未 done 时生效，正常完成的任务不会被覆盖。"""
    def _run():
        time.sleep(seconds)
        with _lock:
            data = _checkin_progress.get(task_id)
            if data and not data.get("done"):
                data = dict(data)
                data["status"] = "done"
                data["done"] = True
                data["results"] = {"error": "任务超时"}
                _checkin_progress[task_id] = data

    t = threading.Thread(target=_run, daemon=True)
    t.start()
```

(Note: `progress.py` already imports `threading`; add `import time`.)

- [ ] **Step 2: Start the watchdog in each blog `_run`**

In `backend/app.py`, after each blog `_run` initializes its progress (`progress.store_progress(task_id, {..., "done": False})`) — specifically at the START of each `_run` body (before `engine = BlogEngine()`) — add:

```python
progress.watchdog(task_id, 900)  # 15 分钟看门狗，防止线程挂死
```

Do this in `blog_scan`, `blog_fetch`, `blog_like` — 3 places. Place it as the first line of each `_run` so it's armed even if `BlogEngine()` construction blocks.

- [ ] **Step 3: Verify**

```bash
python -c "
import sys, time; sys.path.insert(0,'.')
from backend import progress
t = progress.new_task()
progress.store_progress(t, {'status':'pending','done':False})
progress.watchdog(t, 1)
time.sleep(2)
p = progress.get_progress(t)
print('watchdog fired:', p['done'] is True and p['results']['error']=='任务超时')
# guard: a completed task is NOT overwritten
t2 = progress.new_task()
progress.store_progress(t2, {'status':'done','done':True,'results':{'ok':1}})
progress.watchdog(t2, 1)
time.sleep(2)
print('completed not clobbered:', progress.get_progress(t2)['results']=={'ok':1})
"
```
Expected: `watchdog fired: True`, `completed not clobbered: True`.

- [ ] **Step 4: Commit**

```bash
git add backend/progress.py backend/app.py
git commit -m "fix: watchdog force-flips stuck blog tasks to done-with-error"
```

---

### Task 3: Fix A — poll terminal fallback (`frontend/blog.html` + `frontend/index.html`)

**Files:**
- Modify: `frontend/blog.html`
- Modify: `frontend/index.html`

**Interfaces:**
- Produces: a `stopPoll(errorMsg)` helper + `POLL_MAX_MS` const; the poll stops on 404 and on max duration.

- [ ] **Step 1: Add `POLL_MAX_MS` + `stopPoll` to `frontend/blog.html`**

Add near the top of the poll section (before `pollProgress`):

```javascript
const POLL_MAX_MS = 600000; // 10 分钟：进度轮询最长时间，防止任务挂死时无限轮询

// 终止进度轮询并恢复按钮状态
function stopPoll(which, errorMsg) {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  _endTask(which);
  if (errorMsg) toast(errorMsg, "error");
}
```

**Step 2: Rewrite `pollProgress` to be bounded.** The current `pollProgress(task_id, onDone)` needs the task `which` to call `stopPoll`. Change the signature to `pollProgress(which, task_id, onDone)` and update the three call sites (`scanDirectory`, `fetchSelected`, `likeSelected` — they call `pollProgress(task_id, (results) => {...})`). Inside:

```javascript
function pollProgress(which, task_id, onDone) {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  const progressCard = document.getElementById("progressCard");
  const progressDiv = document.getElementById("progress");
  progressCard.style.display = "";
  progressDiv.innerHTML = renderProgressSteps([]);

  const started = Date.now();
  _pollTimer = setInterval(async () => {
    try {
      if (Date.now() - started > POLL_MAX_MS) {
        stopPoll(which, "任务超时，已停止轮询");
        return;
      }
      const p = await API.get(`/api/blog/progress/${task_id}`);
      const bar = renderProgressBar(p.done_count, p.total_count);
      progressDiv.innerHTML = renderProgressSteps(p.steps || []) + bar;
      if (p.done) {
        clearInterval(_pollTimer);
        _pollTimer = null;
        onDone(p.results || {});
      }
    } catch (e) {
      // 404 / 连接失败：任务可能已失效，终止轮询而非无限重试
      stopPoll(which, "任务已失效或服务不可用，已停止轮询");
    }
  }, 500);
}
```

Update the three call sites in `scanDirectory`/`fetchSelected`/`likeSelected` from `pollProgress(task_id, cb)` to `pollProgress("scan"|"fetch"|"like", task_id, cb)`. (Read the current call sites first — they're around blog.html:644, 671, 699.)

- [ ] **Step 3: Apply the same to `frontend/index.html`**

The checkin page's inline poll (around index.html:674-715) has the same infinite-loop pattern. Add the same `POLL_MAX_MS` const and bound the poll: on timeout or 404, `clearInterval(_pollTimer)`, re-enable `#checkinBtn`/`#batchCheckinBtn`, restore button labels, and toast. (The checkin page uses `manualCheckin`'s own button-restore logic — reuse it in a small `stopCheckinPoll(errorMsg)`.)

- [ ] **Step 4: Verify**

```bash
python run.py --no-browser &
# start a task, then check the poll stops on 404 by polling a bogus id:
curl -s "http://127.0.0.1:5000/api/blog/progress/nonexistent"   # 404
```
Manual: start a scan/fetch, then stop the server mid-task → the poll should stop (toast) rather than loop forever. Also: with the server running, a normal task still completes and the poll stops on `done`.

- [ ] **Step 5: Commit**

```bash
git add frontend/blog.html frontend/index.html
git commit -m "fix: bound progress polling with timeout and stop-on-404"
```

---

### Task 4: Fix B — auto-refresh preserves the view (`frontend/blog.html`)

**Files:**
- Modify: `frontend/blog.html`

**Interfaces:**
- Produces: a `loadedAll` flag; the 30s auto-refresh re-fetches `/all` in place when `loadedAll`, else normal `loadArticles()`.

- [ ] **Step 1: Add `loadedAll` flag + set/clear it**

Add `let loadedAll = false;` near the other state (with `loadingAll`). In `loadAll()` after a successful fetch (`data = await API.get(...)`), set `loadedAll = true;`. In `applyFilters()` / `setSort()` (which trigger a fresh page-1 load), set `loadedAll = false;`.

- [ ] **Step 2: Update the auto-refresh callback**

Change the `setInterval` (blog.html:1003-1006) to:

```javascript
setInterval(() => {
  if (_running || loadingAll) return;
  if (loadedAll) {
    loadAll();      // 保持「加载全部」视图，原地刷新全部
  } else {
    loadArticles(); // 普通分页视图，刷新当前页
  }
}, 30000);
```

- [ ] **Step 3: Verify**

Manual: click 加载全部 → wait 30s → the table still shows all rows (not reset to page 1). Filter → wait 30s → view preserved (filtered page 1 refreshes in place). A running task still blocks the refresh (guard intact).

- [ ] **Step 4: Commit**

```bash
git add frontend/blog.html
git commit -m "fix: auto-refresh preserves loaded-all view instead of resetting"
```

---

## Self-Review Notes

- **Spec coverage:** Fix D (T1), Fix C (T2), Fix A (T3), Fix B (T4). All four covered.
- **Type consistency:** `stopPoll(which, msg)` consumed by `pollProgress`; `pollProgress(which, task_id, onDone)` matches the 3 call sites; `loadedAll` set in `loadAll`, cleared in `applyFilters`/`setSort`, read in the refresh; `progress.watchdog(task_id, seconds)` matches the app.py usage. Consistent.
- **Placeholder scan:** no TBD/TODO; every step has concrete code.
