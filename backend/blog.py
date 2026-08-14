# backend/blog.py
"""
博客引擎 — 纯 requests 扫描目录 / 抓取内容 / 批量点赞。
无 Selenium / ChromeDriver 依赖。
"""

import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .checkin import load_config
from .client import get_api_base, login
from . import store

# 目录扫描允许的最大连续失败页数：超过即终止扫描，
# 避免站点持续故障（鉴权过期/宕机/持续 5xx）时后台线程无限翻页。
MAX_CONSECUTIVE_SCAN_ERRORS = 3

# raricy.com 单个账号每日点赞上限
DAILY_LIKE_LIMIT = 100


class BlogEngine:
    """纯 requests 博客引擎 — 扫描目录 / 抓取内容 / 批量点赞"""

    def __init__(self):
        self.config = load_config()
        self._session = None

    # ── Session 管理 ────────────────────────────────────

    def clear_session(self):
        """清空 session，用于切换账号"""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None

    def login(self, username: str, password: str) -> requests.Session:
        """登录并保存已认证 session（供扫描/抓取/点赞使用）"""
        self.clear_session()
        self._session = login(self.config, username, password)
        return self._session

    def _worker_session(self) -> requests.Session:
        """每个工作线程独立的 session：从已登录 session 复制 cookie jar"""
        s = requests.Session()
        s.headers.update(self._session.headers)
        s.cookies.update(self._session.cookies)
        return s

    def _api_url(self, path_key: str, default: str) -> str:
        api_cfg = self.config.get("api", {})
        path = api_cfg.get(path_key, default)
        return get_api_base(self.config) + path

    # ── 目录扫描 ──────────────────────────────────────────
    def scan_directory(self, progress_cb=None):
        if self._session is None:
            raise ValueError("未登录：请先调用 login()")

        def _progress(step, msg, done=None, total_count=None):
            if progress_cb:
                try:
                    progress_cb(step, msg, done=done, total=total_count)
                except Exception:
                    pass

        base = self._api_url("blog_listing_path", "/blog")
        total = new = errors = 0
        page = 1
        consecutive_errors = 0
        seen_pages = set()
        _progress("scan", "正在扫描博客目录...", done=0)

        while True:
            if page in seen_pages:
                break
            seen_pages.add(page)
            url = f"{base}?page={page}"
            try:
                resp = self._session.get(url, timeout=15)
                resp.raise_for_status()
                # requests 对无 charset 的 text/html 默认按 ISO-8859-1 解码，
                # 会乱码中文标题/作者 —— 先修正编码再交给 bs4。
                resp.encoding = resp.apparent_encoding or resp.encoding
                soup = BeautifulSoup(resp.text, "html.parser")
                articles = soup.select("article.blog-item")
                if not articles:
                    break  # end of listing
                rows = []
                for a in articles:
                    link = a.select_one("a.blog-title")
                    if not link or not link.get("href"):
                        continue
                    href = link["href"].strip()
                    if not href.startswith("/blog/"):
                        continue
                    article_id = href.rstrip("/").split("/")[-1]
                    author_el = a.select_one(".blog-author span")
                    category_el = a.select_one(".blog-category-tag")
                    desc_el = a.select_one(".blog-description")
                    likes_el = a.select_one(".blog-likes span")
                    title = link.get_text(strip=True)
                    if not title:
                        continue
                    rows.append({
                        "id": article_id,
                        "title": title,
                        "url": urljoin(get_api_base(self.config), href),
                        "author": author_el.get_text(strip=True) if author_el else "",
                        "category": category_el.get_text(strip=True) if category_el else "",
                        "description": desc_el.get_text(strip=True) if desc_el else "",
                        "likes_count": int(re.sub(r"\D", "", likes_el.get_text() or "0") or "0") if likes_el else 0,
                    })
                # 先查已存在的 id，再统计本次真正新增的行数
                existing_ids = {a["id"] for a in store.get_articles_by_ids([r["id"] for r in rows])}
                store.upsert_articles(rows)
                total += len(rows)
                new += sum(1 for r in rows if r["id"] not in existing_ids)
                _progress("scan", f"第 {page} 页，已收录 {total} 篇", done=total, total_count=None)
                consecutive_errors = 0  # 成功读取一页即清零连续错误计数
                page += 1
            except requests.RequestException as e:
                errors += 1
                consecutive_errors += 1
                _progress("scan_error", f"第 {page} 页获取失败: {e}")
                # 单页失败只跳过该页继续扫描；但连续失败达上限则终止，
                # 否则 page 恒自增，既不命中 seen_pages 也无空页可 break，会一直翻页。
                if consecutive_errors >= MAX_CONSECUTIVE_SCAN_ERRORS:
                    break
                page += 1
                continue

        _progress("done", f"扫描完成，共 {total} 篇")
        return {"total": total, "new": new, "errors": errors}

    # ── 内容抓取 ──────────────────────────────────────────
    def fetch_contents(self, article_ids, progress_cb=None):
        if not article_ids:
            return {"total": 0, "success": 0, "failed": 0}
        if self._session is None:
            raise ValueError("未登录：请先调用 login()")

        def _progress(step, msg, done=None, total_count=None):
            if progress_cb:
                try:
                    progress_cb(step, msg, done=done, total=total_count)
                except Exception:
                    pass

        base = self._api_url("blog_content_path", "/blog/spider/blogs")
        total = len(article_ids)
        success = failed = 0
        _progress("fetch", f"开始抓取 {total} 篇内容...", done=0, total_count=total)

        def _fetch_one(article_id):
            s = self._worker_session()
            try:
                url = f"{base}/{article_id}"
                headers = {"Referer": urljoin(get_api_base(self.config), f"/blog/{article_id}")}
                try:
                    resp = s.get(url, headers=headers, timeout=20)
                    if resp.status_code != 200:
                        return False, article_id, resp.status_code in (500, 502, 503, 504)
                    data = json.loads(resp.content.decode("utf-8"))
                    content = data.get("meta", {}).get("content", "")
                    if content:
                        store.update_content(article_id, content)
                        return True, article_id, False
                    return False, article_id, False
                except (requests.Timeout, requests.ConnectionError):
                    return False, article_id, True
                except requests.RequestException:
                    return False, article_id, False
                except ValueError:
                    # JSON 解析/UTF-8 解码失败：单篇降级为不可重试失败，不中断整批
                    return False, article_id, False
                except sqlite3.Error:
                    # SQLite 写失败（如 database is locked）只降级单篇，不中断整批
                    return False, article_id, False
            finally:
                s.close()

        pending = article_ids
        for _round in range(5):
            if not pending:
                break
            retry = []
            with ThreadPoolExecutor(max_workers=5) as ex:
                futs = {ex.submit(_fetch_one, i): i for i in pending}
                for fut in as_completed(futs):
                    ok, aid, retryable = fut.result()
                    if ok:
                        success += 1
                    elif retryable:
                        retry.append(aid)  # 先不计入失败，重试后再定
                    else:
                        failed += 1
                    # 每完成一篇即更新一次进度，进度条实时刷新
                    _progress("fetch", f"已抓取 {success} 篇，待重试 {len(retry)}", done=success + failed, total_count=total)
            pending = retry
            if pending:
                time.sleep(1)
        failed += len(pending)  # 重试满轮仍未成功的，最终计入一次失败
        _progress("done", f"抓取完成：成功 {success}，失败 {failed}", done=success + failed, total_count=total)
        return {"total": total, "success": success, "failed": failed}

    # ── 批量点赞 ──────────────────────────────────────────
    def like_articles(self, article_ids, username, password, progress_cb=None):
        def _progress(step, msg, done=None, total_count=None):
            if progress_cb:
                try:
                    progress_cb(step, msg, done=done, total=total_count)
                except Exception:
                    pass

        if not article_ids:
            return {"total": 0, "success": 0, "failed": 0, "skipped": 0,
                    "limited": 0, "used": 0, "available": 0, "limit": DAILY_LIKE_LIMIT}

        # 每日点赞上限：先统计该账号今日已用次数，再据此截断待点赞列表
        requested = len(article_ids)
        used_before = store.count_today_likes(username)
        available = max(0, DAILY_LIKE_LIMIT - used_before)
        limited = max(0, requested - available)
        if available <= 0:
            # 今日额度已用完：不登录、不执行任何点赞请求
            return {"total": requested, "success": 0, "failed": 0, "skipped": 0,
                    "limited": limited, "used": used_before, "available": 0,
                    "limit": DAILY_LIKE_LIMIT}
        if limited > 0:
            article_ids = article_ids[:available]

        self.login(username, password)
        base = self._api_url("blog_like_path", "/blog")
        total = len(article_ids)          # 实际尝试的篇数（<= available）
        success = failed = skipped = 0
        _progress("like", f"开始为 {total} 篇点赞（今日剩余 {available} 次）...", done=0, total_count=total)

        def _like_one(article_id):
            if store.has_liked(article_id, username):
                return "skipped", article_id, False
            s = self._worker_session()
            try:
                url = f"{base}/{article_id}/like"
                headers = {"Referer": urljoin(get_api_base(self.config), f"/blog/{article_id}")}
                try:
                    resp = s.post(url, headers=headers, timeout=5)
                    # 站点点赞接口的成败以响应 JSON 的 code 字段为准（见 raricy.com 前端
                    # like-manager.js：`data.code === 200`），而非 HTTP 状态码。未登录时
                    # 站点可能 302 重定向到登录页，requests 跟随重定向后 status_code 仍是 200，
                    # 若只看状态码会把「未登录/失败」误判为点赞成功（即点赞实际未生效）。
                    try:
                        data = resp.json()
                    except ValueError:
                        data = {}
                    ok = data.get("code") == 200
                    message = data.get("message") or f"HTTP {resp.status_code}"
                    store.record_like(article_id, username, ok, message)
                    return ok, article_id, resp.status_code in (500, 502, 503, 504)
                except (requests.Timeout, requests.ConnectionError):
                    return False, article_id, True
                except requests.RequestException:
                    return False, article_id, False
                except sqlite3.Error:
                    # SQLite 写失败（如 database is locked）只降级单篇，不中断整批
                    return False, article_id, False
            finally:
                s.close()

        pending = article_ids
        for _round in range(5):
            if not pending:
                break
            retry = []
            with ThreadPoolExecutor(max_workers=20) as ex:
                futs = {ex.submit(_like_one, i): i for i in pending}
                for fut in as_completed(futs):
                    status, aid, retryable = fut.result()
                    if status == "skipped":
                        skipped += 1
                    elif status is True:
                        success += 1
                    elif retryable:
                        retry.append(aid)  # 先不计入失败，重试后再定
                    else:
                        failed += 1
                    # 每完成一篇即更新一次进度，进度条实时刷新（done 计入跳过，保证进度条可达 100%）
                    _progress("like", f"已点赞 {success} 篇，待重试 {len(retry)}", done=success + failed + skipped, total_count=total)
            pending = retry
            if pending:
                time.sleep(1)
        failed += len(pending)  # 重试满轮仍未成功的，最终计入一次失败
        _progress("done", f"点赞完成：成功 {success}，失败 {failed}，跳过 {skipped}", done=success + failed + skipped, total_count=total)
        used_after = store.count_today_likes(username)
        return {"total": requested, "success": success, "failed": failed, "skipped": skipped,
                "limited": limited, "used": used_after,
                "available": max(0, DAILY_LIKE_LIMIT - used_after),
                "limit": DAILY_LIKE_LIMIT}
