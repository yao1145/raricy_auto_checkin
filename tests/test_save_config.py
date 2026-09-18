"""
`save_config()` 的写入顺序：accounts 先写，config.json 后写。

为什么顺序有讲究：这两个文件没法做成一个事务，只能挑一种「失败时留下什么」。
accounts 那步要加密 + 原子替换，失败面比写一个 JSON 大得多。它先失败的话
config.json 保持原样 —— 用户看到 500、重试即可，状态是自洽的。
反过来先写 config.json，就会出现「面板报保存失败，配置其实已经改了」的静默偏差：
配置看着是旧的，行为是新的，最难排查。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import app

ORIGINAL = {"site": {"username": "old"}, "schedule": {"enabled": True}}
INCOMING = {
    "site": {"username": "new"},
    "schedule": {"enabled": False},
    "accounts": [{"username": "alice", "password": "pw", "enabled": True}],
}


class SaveConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "config.json"
        self.cfg.write_text(json.dumps(ORIGINAL), encoding="utf-8")
        self.patch = mock.patch.object(app, "CONFIG_PATH", self.cfg)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_accounts_failure_leaves_config_untouched(self):
        """accounts 写失败时，config.json 不能被动过。"""
        before = self.cfg.read_text(encoding="utf-8")
        with mock.patch.object(app, "save_accounts", side_effect=OSError("simulated EBUSY")):
            with self.assertRaises(OSError):
                app.save_config(json.loads(json.dumps(INCOMING)))
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), before)

    def test_happy_path_writes_accounts_and_config(self):
        saved = {}
        with mock.patch.object(app, "save_accounts", side_effect=lambda a: saved.update(accts=a)):
            app.save_config(json.loads(json.dumps(INCOMING)))

        self.assertEqual(saved["accts"], INCOMING["accounts"])
        on_disk = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["site"]["username"], "new")
        self.assertFalse(on_disk["schedule"]["enabled"])

    def test_accounts_never_leak_into_config_json(self):
        """凭据只进 accounts.enc；config.json 里出现明文密码就是回归。"""
        with mock.patch.object(app, "save_accounts"):
            app.save_config(json.loads(json.dumps(INCOMING)))
        self.assertNotIn("accounts", self.cfg.read_text(encoding="utf-8"))

    def test_no_accounts_key_still_writes_config(self):
        """不带 accounts 的局部更新（dot-path 分支）不应触发账号写入。"""
        with mock.patch.object(app, "save_accounts") as saver:
            app.save_config({"site": {"username": "only-config"}})
        saver.assert_not_called()
        self.assertEqual(
            json.loads(self.cfg.read_text(encoding="utf-8"))["site"]["username"],
            "only-config",
        )


if __name__ == "__main__":
    unittest.main()
