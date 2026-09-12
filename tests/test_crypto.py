import os
import tempfile
import unittest
from pathlib import Path

from backend.crypto import (
    AccountsDecryptError,
    decrypt_bytes,
    encrypt_bytes,
    load_or_create_key,
)


class TestKeyFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_path = Path(self.tmp.name) / ".accounts.key"

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_key_when_missing(self):
        key = load_or_create_key(self.key_path)
        self.assertTrue(self.key_path.exists())
        self.assertTrue(len(key) > 0)
        # 同一个文件第二次读出来必须是同一把钥匙
        self.assertEqual(key, load_or_create_key(self.key_path))

    def test_empty_key_file_is_rejected(self):
        self.key_path.write_bytes(b"")
        with self.assertRaises(AccountsDecryptError):
            load_or_create_key(self.key_path)

    @unittest.skipIf(os.name == "nt", "Windows 的 chmod 不构成权限隔离")
    def test_key_file_is_0600(self):
        load_or_create_key(self.key_path)
        mode = self.key_path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = load_or_create_key(Path(self.tmp.name) / ".accounts.key")

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        data = '{"账号": "中文也要能过"}'.encode("utf-8")
        self.assertEqual(decrypt_bytes(encrypt_bytes(data, self.key), self.key), data)

    def test_wrong_key_raises(self):
        other = load_or_create_key(Path(self.tmp.name) / ".other.key")
        token = encrypt_bytes(b"secret", self.key)
        with self.assertRaises(AccountsDecryptError):
            decrypt_bytes(token, other)

    def test_tampered_token_raises(self):
        token = bytearray(encrypt_bytes(b"secret", self.key))
        token[-1] ^= 0x01  # 翻转最后一字节
        with self.assertRaises(AccountsDecryptError):
            decrypt_bytes(bytes(token), self.key)

    def test_malformed_key_raises(self):
        with self.assertRaises(AccountsDecryptError):
            decrypt_bytes(b"whatever", b"not-a-valid-fernet-key")


if __name__ == "__main__":
    unittest.main()
