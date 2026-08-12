"""
打卡引擎 — 纯 requests 实现登录、打卡和运势抽取。
无 Selenium / ChromeDriver 依赖。
"""

import json
import random
import time
from datetime import datetime
from pathlib import Path

import requests

from .client import (
    build_session, login as client_login, get_api_base,
    CheckinError, AlreadyCheckedInError, LoginFailedError, NetworkError,
)

# ── 项目路径 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
CONFIG_PATH = BASE_DIR / "config.json"
ACCOUNTS_PATH = BASE_DIR / "accounts.json"


# ── 配置工具 ──────────────────────────────────────────────
def load_config() -> dict:
    """加载配置文件（accounts 从 accounts.json 合并，保持返回结构不变）"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    accounts = load_accounts()
    if accounts is not None:
        config["accounts"] = accounts
    return config


def load_accounts() -> list | None:
    """读取账号列表。文件不存在返回 None（兼容旧配置内嵌 accounts）。"""
    if not ACCOUNTS_PATH.exists():
        return None
    with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_accounts(accounts: list) -> None:
    """保存账号列表到 accounts.json"""
    with open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


# ── 打卡引擎 ──────────────────────────────────────────────
class CheckinEngine:
    """纯 requests 打卡引擎 — 无浏览器依赖"""

    def __init__(self):
        self.config = load_config()
        self.session: requests.Session | None = None

    # ── Session 管理 ────────────────────────────────────

    def _get_api_base(self) -> str:
        """从 checkin_url 提取 API 基础 URL（scheme + netloc）"""
        return get_api_base(self.config)

    def _build_session(self) -> requests.Session:
        """创建带浏览器伪装头的 requests.Session"""
        return build_session(self.config)

    def clear_session(self):
        """清空 session，用于切换账号"""
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = None

    def quit(self):
        """关闭 session（兼容旧接口）"""
        self.clear_session()

    # ── 登录流程（requests）──────────────────────────────

    def _login(self, username: str, password: str) -> requests.Session:
        """
        POST 登录到 /auth/login，返回已认证的 session。

        策略（实现见 client.login）:
        1. GET 登录页 → 提取可能的 CSRF token
        2. POST 表单数据 (username, password)
        3. 验证登录成功（检查响应 / 重定向）
        """
        return client_login(self.config, username, password)

    # ── HTTP API 调用 ────────────────────────────────────

    def _api_checkin(self, session: requests.Session) -> dict:
        """
        通过 HTTP API 执行打卡。
        POST /checkin/api/do-checkin
        """
        api_base = self._get_api_base()
        api_cfg = self.config.get("api", {})
        checkin_path = api_cfg.get("checkin_path", "/checkin/api/do-checkin")
        url = f"{api_base}{checkin_path}"

        resp = session.post(url, json={}, timeout=15)
        try:
            data = resp.json()
        except ValueError:
            raise NetworkError(f"打卡API返回非JSON: {resp.status_code}")
        return data

    def _api_claim_fortune(self, session: requests.Session,
                           chosen_index: int | None = None) -> dict | None:
        """
        通过 HTTP API 抽取运势卡片。
        POST /checkin/api/claim-fortune
        """
        api_base = self._get_api_base()
        api_cfg = self.config.get("api", {})
        fortune_path = api_cfg.get("fortune_path", "/checkin/api/claim-fortune")
        url = f"{api_base}{fortune_path}"

        fortune_cfg = self.config.get("fortune", {})

        if chosen_index is None:
            card_index = fortune_cfg.get("card_index", "random")
            if card_index == "random":
                chosen_index = random.randint(0, 4)
            else:
                chosen_index = int(card_index) % 5

        fortune_result = {
            "handled": False,
            "card_selected": chosen_index,
            "total_cards": 5,
            "result_value": None,
            "result_desc": "",
            "result_text": "",
        }

        try:
            resp = session.post(
                url,
                json={"chosen_index": chosen_index},
                timeout=15,
            )
            data = resp.json()

            if data.get("code") == 200:
                fortune_value = data.get("fortune_value")
                pool = data.get("pool", [])
                fortune_result["handled"] = True
                fortune_result["result_value"] = str(fortune_value) if fortune_value is not None else ""
                fortune_result["result_text"] = str(fortune_value) if fortune_value is not None else ""
                fortune_result["pool"] = pool
            else:
                fortune_result["result_text"] = data.get("message", "运势抽取失败")

        except Exception as e:
            fortune_result["result_text"] = f"运势API请求异常: {e}"

        return fortune_result

    # ── 打卡流程 ────────────────────────────────────────

    def execute(self, username: str = "", password: str = "",
                progress_callback=None) -> dict:
        """
        执行完整打卡流程（纯 requests，无浏览器）。

        1. requests 登录 (POST /auth/login)
        2. HTTP API 打卡 (POST /checkin/api/do-checkin)
        3. HTTP API 运势卡片 (POST /checkin/api/claim-fortune)

        Args:
            username: 登录用户名
            password: 登录密码
            progress_callback: callable(step, message)
        """
        def _progress(step: str, message: str):
            if progress_callback:
                try:
                    progress_callback(step, message)
                except Exception:
                    pass

        # 兼容旧配置
        if not username:
            username = self.config.get("site", {}).get("username", "")
        if not password:
            password = self.config.get("site", {}).get("password", "")

        if not username or not password:
            return {
                "success": False,
                "message": "缺少用户名或密码",
                "already_checked": False,
                "fortune": None,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "duration_seconds": 0,
                "account": username,
                "steps": [{"status": "error", "message": "缺少用户名或密码",
                           "time": datetime.now().strftime("%H:%M:%S")}],
            }

        start_time = time.time()
        result = {
            "success": False,
            "message": "",
            "already_checked": False,
            "fortune": None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": 0,
            "account": username,
            "steps": [],
        }

        def _add_step(status: str, message: str):
            result["steps"].append({
                "status": status,
                "message": message,
                "time": datetime.now().strftime("%H:%M:%S"),
            })

        try:
            # ── 阶段1: 登录 ───────────────────────────────
            _progress("login", "正在登录...")
            _add_step("running", "正在登录...")

            self.session = self._login(username, password)

            _progress("logged_in", "登录成功")
            _add_step("done", "登录成功")

            # ── 阶段2: 打卡 API ───────────────────────────
            _progress("checking", "正在打卡...")
            _add_step("running", "正在打卡...")

            try:
                checkin_data = self._api_checkin(self.session)
            except requests.RequestException as e:
                raise NetworkError(f"打卡API请求失败: {e}")

            code = checkin_data.get("code")

            if code == 401:
                _progress("error", "登录已过期")
                _add_step("error", "登录已过期")
                raise LoginFailedError("登录已过期，Session 失效")

            if checkin_data.get("already_checked"):
                result["already_checked"] = True
                result["success"] = True
                result["message"] = "今日已打卡，无需重复操作"
                if checkin_data.get("total_count"):
                    result["total_days"] = checkin_data["total_count"]
                _progress("done", "今日已打卡")
                _add_step("done", "今日已打卡")
                return result

            if code != 200:
                msg = checkin_data.get("message", "打卡API返回异常")
                _progress("error", msg)
                _add_step("error", msg)
                result["message"] = msg
                return result

            _progress("checkin_done", "打卡成功")
            _add_step("done", "打卡成功")
            result["success"] = True
            result["message"] = checkin_data.get("message", "打卡成功 ✓")

            # ── 阶段3: 运势卡片（可选）───────────────────
            fortune_cfg = self.config.get("fortune", {})
            show_fortune = checkin_data.get("show_fortune", False)
            fortune_pending = checkin_data.get("fortune_pending", False)

            if fortune_cfg.get("enabled", False) and (show_fortune or fortune_pending):
                _progress("fortune", "正在抽取运势...")
                _add_step("running", "正在抽取运势卡片...")

                fortune_result = self._api_claim_fortune(self.session)
                if fortune_result:
                    result["fortune"] = fortune_result
                    if fortune_result.get("handled"):
                        _progress("fortune_done",
                                  f"运势: {fortune_result.get('result_text', '')}")
                        _add_step("done",
                                  f"运势卡片: {fortune_result.get('result_text', '')}")
                    else:
                        _add_step("done",
                                  "运势: " + fortune_result.get("result_text", "未获取"))

            _progress("done", "打卡完成")

        except AlreadyCheckedInError:
            result["already_checked"] = True
            result["success"] = True
            result["message"] = "今日已打卡"
            _add_step("done", "今日已打卡")
        except LoginFailedError as e:
            result["message"] = str(e)
            _add_step("error", str(e))
        except NetworkError as e:
            result["message"] = str(e)
            _add_step("error", str(e))
        except Exception as e:
            result["message"] = f"未知错误: {e}"
            _add_step("error", str(e))
        finally:
            result["duration_seconds"] = round(time.time() - start_time, 1)

        return result


# ── 便捷函数 ──────────────────────────────────────────────
def create_engine() -> CheckinEngine:
    """工厂函数：创建打卡引擎实例"""
    return CheckinEngine()


def get_enabled_accounts() -> list[dict]:
    """
    获取所有启用的账号列表。
    兼容旧配置：如果 config 中无 accounts 数组，回退到 site.username/password。
    """
    config = load_config()
    accounts = config.get("accounts", [])
    if accounts:
        return [a for a in accounts if a.get("enabled", True)]
    # 兼容旧配置
    site = config.get("site", {})
    username = site.get("username", "")
    password = site.get("password", "")
    if username:
        return [{"username": username, "password": password, "enabled": True}]
    return []


# ── 兼容性 re-export（保持旧导入不变）──────────────────────
from .client import CheckinError, AlreadyCheckedInError, LoginFailedError, NetworkError  # noqa: E402,F401
