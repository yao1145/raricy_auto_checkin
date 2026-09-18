"""query_articles() 按标题搜索的单元测试。

重点钉住 LIKE 通配符转义：`_` 和 `%` 是 LIKE 的元字符，不转义时搜「_」会
静默命中全部标题 —— 不报错、不抛异常，只是结果错，属于最难被发现的那类 bug。
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import store

# (id, title, author)
ARTICLES = [
    ("a1", "Next.js 入门", "alice"),
    ("a2", "next 教程", "alice"),
    ("a3", "用 Next 搭建博客", "bob"),
    ("a4", "C++_primer 笔记", "bob"),
    ("a5", "进度 100% 达成", "alice"),
    ("a6", "Vue 3 实战", "bob"),
]


class TitleSearchTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "blog.db"
        # store._conn() 每次都调 get_db_path()，后者读的是模块级全局 BLOG_DB_PATH，
        # 替换该属性即可把测试隔离到临时库。
        self.patch = mock.patch.object(store, "BLOG_DB_PATH", db)
        self.patch.start()
        store.init_db()
        store.upsert_articles([
            {"id": i, "title": t, "url": f"https://example.test/blog/{i}",
             "author": a, "category": "tech", "description": "", "likes_count": 0}
            for i, t, a in ARTICLES
        ])

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def titles(self, **kwargs):
        rows, _total = store.query_articles(**kwargs)
        return {r["title"] for r in rows}

    def test_substring_match_is_case_insensitive(self):
        self.assertEqual(
            self.titles(title="next"),
            {"Next.js 入门", "next 教程", "用 Next 搭建博客"},
        )

    def test_underscore_is_escaped_not_a_wildcard(self):
        # 不转义时 '_' 匹配任意单字符，会命中全部 6 篇
        self.assertEqual(self.titles(title="_"), {"C++_primer 笔记"})

    def test_percent_is_escaped_not_a_wildcard(self):
        self.assertEqual(self.titles(title="%"), {"进度 100% 达成"})

    def test_search_ands_with_author_filter(self):
        # 同时含 next（不分大小写）且作者为 bob 的只有这一篇
        self.assertEqual(self.titles(title="next", author="bob"), {"用 Next 搭建博客"})

    def test_absent_title_returns_all(self):
        self.assertEqual(len(self.titles()), len(ARTICLES))
