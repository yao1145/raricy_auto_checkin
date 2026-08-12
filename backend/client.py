"""
共享纯 requests 登录客户端 — 供打卡引擎与博客引擎复用。
无 Selenium / ChromeDriver 依赖。
"""

import re
from urllib.parse import urljoin, urlparse

import requests


class CheckinError(Exception):
    """打卡相关异常的基类"""


class AlreadyCheckedInError(CheckinError):
    """今日已打卡"""


class LoginFailedError(CheckinError):
    """登录失败"""


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


def _extract_csrf(html: str) -> str | None:
    patterns = [
        r'<input[^>]+name=["\']csrf_token["\'][^>]+value=["\']([^"\']+)',
        r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)',
        r'name=["\']_csrf_token["\'][^>]+value=["\']([^"\']+)',
        r'csrf_token\s*[:=]\s*["\']([^"\']+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _verify_login(session: requests.Session, checkin_url: str) -> bool:
    if not checkin_url:
        return True
    try:
        resp = session.get(checkin_url, timeout=10, allow_redirects=True)
        final_url = resp.url.lower()
        if "/auth/login" in final_url or "/login" in final_url:
            return False
        text = resp.text.lower()
        if '<form id="loginform"' in text or 'id="loginform"' in text:
            return False
        return True
    except requests.RequestException:
        return False


def login(config: dict, username: str, password: str) -> requests.Session:
    """POST login to /auth/login, return authenticated session (form-first, JSON fallback)."""
    api_base = get_api_base(config)
    site = config["site"]
    api_cfg = config.get("api", {})
    login_path = api_cfg.get("login_path", "/auth/login")
    login_url = site.get("login_url", urljoin(api_base, "/auth/login"))
    checkin_url = site.get("checkin_url", "")

    session = build_session(config)

    try:
        resp = session.get(login_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise NetworkError(f"无法访问登录页: {e}")

    csrf_token = _extract_csrf(resp.text)
    login_data = {"username": username, "password": password, "next": ""}
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Referer": login_url}
    if csrf_token:
        login_data["csrf_token"] = csrf_token

    try:
        session.post(login_url, data=login_data, headers=headers, timeout=15, allow_redirects=True)
    except requests.RequestException as e:
        raise NetworkError(f"登录请求失败: {e}")

    if not _verify_login(session, checkin_url):
        json_headers = {"Content-Type": "application/json", "Referer": login_url, "X-Requested-With": "XMLHttpRequest"}
        try:
            session.post(login_url, json={"username": username, "password": password}, headers=json_headers, timeout=15, allow_redirects=True)
            if not _verify_login(session, checkin_url):
                raise LoginFailedError(f"登录失败：账号 {username} 的用户名或密码错误")
        except requests.RequestException as e:
            raise LoginFailedError(f"登录失败: {e}")

    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    })
    return session
