"""
钉住博客正文抓取的 core+ 门槛。

为什么这条值一个测试：站点在 2026-09-18（commit 5eace12）把 `GET /api/spider/blogs/:id`
等五个读口从「完全免认证」收紧为 core+，非 core 账号一律 403「需要核心用户权限」。
而抓取循环对非 200 的处理是**计入失败、不重试、不抛异常**，所以少了这层前置校验时，
整批正文会变成「成功 0，失败 N」的静默空转 —— 面板上与站点故障、网络不通长得一模一样，
只能靠翻代码才发现是权限问题。这里锁死两件事：

  1. 登录时把站点返回的 role 带走（login() 里曾经把整个 user 字段丢掉）；
  2. 正文抓取前按角色放行/拦截，且选账号时跳过非 core 的账号。

纯标准库 + mock：tests/ 不引入新依赖，也不发真实请求、不碰 runtime/blog.db。
"""

import json
import unittest
from unittest import mock

from backend.blog import BlogEngine
from backend.client import CorePermissionError, LoginFailedError, is_core_role, session_role

CONFIG = {"site": {"checkin_url": "https://raricy.com/checkin"}}


class _FakeResp:
    """_fetch_one 读的是 .content 字节流（不是 .json()），故两个都备上"""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def json(self):
        return self._payload


class _FakeLoginSession:
    """登录用的最小 Session 替身：login() 只用到 headers / post / get"""

    def __init__(self, role="core"):
        self.headers = {}
        self.raricy_role = role

    def post(self, *args, **kwargs):
        return _FakeResp(200, {
            "code": 200,
            "message": "登录成功",
            "user": {"id": 1, "username": "u", "role": self.raricy_role},
        })

    def get(self, *args, **kwargs):
        return _FakeResp(200, {"code": 200})  # _verify_login 的探针请求


class _FakeContentSession:
    """抓取正文用的 worker session 替身"""

    def __init__(self, content="# 正文"):
        self._content = content

    def get(self, *args, **kwargs):
        return _FakeResp(200, {"content": self._content})

    def close(self):
        pass


class BlogCoreGateTest(unittest.TestCase):
    def _engine(self, role="core"):
        """跳过 __init__ 里对真实配置/账号文件的读取，手工造一个已登录的引擎"""
        with mock.patch("backend.blog.load_config", return_value=CONFIG):
            engine = BlogEngine()
        engine._session = _FakeLoginSession(role)
        engine._username = "someone"
        return engine

    def test_login_records_role_from_response(self):
        """站点返回的 user.role 必须跟着 session 走 —— 这是判断能否抓正文的唯一依据"""
        with mock.patch("backend.blog.load_config", return_value=CONFIG), \
                mock.patch("backend.client.build_session", return_value=_FakeLoginSession("admin")):
            engine = BlogEngine()
            engine.login("someone", "pw")
        self.assertEqual(session_role(engine._session), "admin")
        self.assertEqual(engine._username, "someone")

    def test_core_role_covers_core_admin_owner_only(self):
        for role in ("core", "admin", "owner"):
            self.assertTrue(is_core_role(role), role)
        for role in ("user", "", None, "vip"):
            self.assertFalse(is_core_role(role), role)

    def test_fetch_refuses_non_core_account(self):
        """非 core 账号要在发请求之前就被拦下，而不是让每篇攒一次 403 失败"""
        engine = self._engine(role="user")
        with self.assertRaises(CorePermissionError) as ctx:
            engine.fetch_contents(["abc-123"])
        message = str(ctx.exception)
        self.assertIn("someone", message)  # 得点名是哪个账号，否则没法排查
        self.assertIn("user", message)

    def test_fetch_proceeds_for_core_account(self):
        engine = self._engine(role="core")
        with mock.patch.object(BlogEngine, "_worker_session",
                               return_value=_FakeContentSession()), \
                mock.patch("backend.blog.store") as store:
            result = engine.fetch_contents(["abc-123"])
        self.assertEqual(result, {"total": 1, "success": 1, "failed": 0})
        store.update_content.assert_called_once_with("abc-123", "# 正文")

    def test_login_first_core_skips_non_core_accounts(self):
        """面板调不了账号顺序，所以不能写死 accounts[0] —— 得往后找到真正够档的那个"""
        accounts = [{"username": n, "password": "p"} for n in ("a", "b", "c")]
        roles = {"a": "user", "b": "user", "c": "core"}
        engine = self._engine(role="user")

        def fake_login(username, password):
            engine._username = username
            engine._session = _FakeLoginSession(roles[username])
            return engine._session

        with mock.patch.object(BlogEngine, "login", side_effect=fake_login):
            picked = engine.login_first_core(accounts)
        self.assertEqual(picked["username"], "c")
        self.assertEqual(engine._username, "c")

    def test_login_first_core_tolerates_dead_credentials(self):
        """某个账号密码失效不该挡住后面那个真正的 core 账号"""
        accounts = [{"username": n, "password": "p"} for n in ("dead", "good")]
        engine = self._engine(role="user")

        def fake_login(username, password):
            if username == "dead":
                raise LoginFailedError("账号或密码错误")
            engine._username = username
            engine._session = _FakeLoginSession("core")
            return engine._session

        with mock.patch.object(BlogEngine, "login", side_effect=fake_login):
            picked = engine.login_first_core(accounts)
        self.assertEqual(picked["username"], "good")

    def test_login_first_core_reports_every_attempt(self):
        """全都不够档时，报错要列全试过谁、各自什么角色"""
        accounts = [{"username": n, "password": "p"} for n in ("a", "b")]
        engine = self._engine(role="user")
        with mock.patch.object(BlogEngine, "login",
                               side_effect=lambda u, p: _FakeLoginSession("user")):
            with self.assertRaises(CorePermissionError) as ctx:
                engine.login_first_core(accounts)
        message = str(ctx.exception)
        self.assertIn("a", message)
        self.assertIn("b", message)
        self.assertIn("user", message)


if __name__ == "__main__":
    unittest.main()
