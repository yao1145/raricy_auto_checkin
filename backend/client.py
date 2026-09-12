"""
共享纯 requests 登录客户端 — 供打卡引擎与博客引擎复用。
无 Selenium / ChromeDriver 依赖。
"""

from urllib.parse import urljoin, urlparse

import requests


class CheckinError(Exception):
    """打卡相关异常的基类"""


class AlreadyCheckedInError(CheckinError):
    """今日已打卡"""


class LoginFailedError(CheckinError):
    """登录失败"""


class RateLimitedError(CheckinError):
    """登录触发站点限频（429）—— 与密码错误区分开，重试只会延长封禁窗口"""


class NetworkError(CheckinError):
    """网络超时或不可达"""


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


def get_api_base(config: dict) -> str:
    checkin_url = config["site"].get("checkin_url", "")
    if checkin_url:
        parsed = urlparse(checkin_url)
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def build_session(config: dict) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": get_api_base(config),
        "Referer": config["site"].get("checkin_url", get_api_base(config)),
        "Connection": "keep-alive",
    })
    return s


def api_url(config: dict, key: str, default: str) -> str:
    """按 config.api 里的相对路径拼出完整 URL（路径带不带前导 / 都行）。"""
    path = config.get("api", {}).get(key) or default
    return urljoin(get_api_base(config) + "/", path.lstrip("/"))


def _verify_login(session: requests.Session, config: dict) -> bool:
    """
    登录后用 GET 打卡接口确认会话真的生效。

    为什么不只看登录接口的 code==200：会话 cookie 在 Secure 标记与反代协议不一致时
    会被客户端静默丢弃（站点 session.ts 里专门记录了「返回 200 登录成功，但会话不粘、
    刷新仍未登录，且无任何报错」这个坑）。只有再发一次带 cookie 的请求才能暴露它。
    """
    checkin_path = config.get("api", {}).get("checkin_path") or "/api/checkin"
    try:
        resp = session.get(api_url(config, "checkin_path", checkin_path), timeout=10)
        return resp.status_code == 200 and resp.json().get("code") == 200
    except (requests.RequestException, ValueError):
        return False


def login(config: dict, username: str, password: str) -> requests.Session:
    """
    POST /api/auth/login（JSON）→ 返回已认证的 session。

    站点已从 Flask 迁到 Next.js，登录接口随之搬家：只接受 JSON body
    {username, password}（用户名或邮箱均可），返回 {code, message, user}
    并下发 JWT cookie（raricy_session，30 天）。失败码：
    400 参数缺失 / 401 账号或密码错误 / 429 触发登录限频。
    """
    login_url = api_url(config, "login_path", "/api/auth/login")
    # 登录页地址只用于 Referer，接口本身在 /api 下
    page_url = config["site"].get("login_url") or get_api_base(config)

    session = build_session(config)

    try:
        resp = session.post(
            login_url,
            json={"username": username, "password": password},
            headers={"Referer": page_url},
            timeout=15,
        )
    except requests.RequestException as e:
        raise NetworkError(f"登录请求失败: {e}")

    try:
        data = resp.json()
    except ValueError:
        raise LoginFailedError(f"登录接口返回非JSON（HTTP {resp.status_code}）")

    code = data.get("code")
    if code == 429:
        # 站点对登录失败做了双维度限频（同用户名 15 分钟 100 次 / 同 IP 300 次），
        # 且只统计失败。这不是密码错，继续重试只会把封禁窗口一直续上。
        raise RateLimitedError(data.get("message") or "登录尝试过于频繁，请稍后重试")
    if code != 200:
        raise LoginFailedError(f"登录失败：{data.get('message') or '账号或密码错误'}")

    if not _verify_login(session, config):
        raise LoginFailedError(f"登录成功但会话未生效：{username}")

    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    })
    return session
