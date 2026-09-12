import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import checkin
from backend.crypto import AccountsDecryptError, load_or_create_key

ACCOUNTS = [
    {"username": "alice", "password": "pw-a", "enabled": True},
    {"username": "bob", "password": "pw-b", "enabled": False},
]


class AccountsStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.enc = root / "accounts.enc"
        self.plain = root / "accounts.json"
        self.key = root / ".accounts.key"
        self.patches = [
            mock.patch.object(checkin, "ACCOUNTS_ENC_PATH", self.enc),
            mock.patch.object(checkin, "ACCOUNTS_PLAIN_PATH", self.plain),
            mock.patch("backend.crypto.KEY_PATH", self.key),
        ]
        for p in self.patches:
            p.start()
        load_or_create_key(self.key)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write_plain(self):
        self.plain.write_text(json.dumps(ACCOUNTS, ensure_ascii=False), encoding="utf-8")


class TestLoad(AccountsStoreTestCase):
    def test_roundtrip(self):
        checkin.save_accounts(ACCOUNTS)
        self.assertTrue(self.enc.exists())
        self.assertEqual(checkin.load_accounts(), ACCOUNTS)

    def test_nothing_present_returns_none(self):
        self.assertIsNone(checkin.load_accounts())

    def test_plaintext_fallback_when_no_ciphertext(self):
        self.write_plain()
        # 回退必须伴随告警，否则用户不会知道自己在跑明文
        with self.assertLogs("backend.checkin", level="WARNING") as captured:
            self.assertEqual(checkin.load_accounts(), ACCOUNTS)
        self.assertIn("明文账号文件", "\n".join(captured.output))

    def test_corrupt_ciphertext_never_falls_back_to_plaintext(self):
        checkin.save_accounts(ACCOUNTS)
        self.write_plain()  # 同时摆一份明文，诱使实现走降级路径
        raw = bytearray(self.enc.read_bytes())
        raw[-1] ^= 0x01
        self.enc.write_bytes(bytes(raw))
        with self.assertRaises(AccountsDecryptError):
            checkin.load_accounts()

    def test_wrong_key_raises_instead_of_returning_empty(self):
        checkin.save_accounts(ACCOUNTS)
        self.key.write_bytes(load_or_create_key(Path(self.tmp.name) / "other.key"))
        with self.assertRaises(AccountsDecryptError):
            checkin.load_accounts()


class TestSave(AccountsStoreTestCase):
    def test_atomic_write_leaves_no_tmp_file(self):
        checkin.save_accounts(ACCOUNTS)
        leftovers = list(self.enc.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_save_then_load_after_key_rotation_raises(self):
        checkin.save_accounts(ACCOUNTS)
        self.key.write_bytes(load_or_create_key(Path(self.tmp.name) / "rotated.key"))
        with self.assertRaises(AccountsDecryptError):
            checkin.load_accounts()


if __name__ == "__main__":
    unittest.main()
