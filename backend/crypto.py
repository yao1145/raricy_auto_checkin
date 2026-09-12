# backend/crypto.py
"""
账号文件加密 —— Fernet 对称加密 + 密钥文件管理。

【防护边界，别夸大】密钥与密文同机时，加密防的是「密文文件单独泄露」：
误传到别处、被截图、备份盘被拿走、误提交进仓库。它挡不住已经拿到主机权限、
或能看到进程环境的人。要挡后者得上手输口令或外部 KMS，那与无人值守定时打卡冲突。
"""

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

RUNTIME_DIR = Path(__file__).resolve().parent.parent / "runtime"
KEY_PATH = RUNTIME_DIR / ".accounts.key"


class AccountsDecryptError(Exception):
    """密文或密钥不可用 —— 调用方必须直接失败，绝不降级为空账号列表。"""


def load_or_create_key(key_path: Path | None = None) -> bytes:
    """读取密钥，不存在则生成并落盘。文件为空视为损坏，直接报错。"""
    path = key_path or KEY_PATH
    if path.exists():
        raw = path.read_bytes().strip()
        if not raw:
            raise AccountsDecryptError(f"密钥文件为空（{path}），无法解密账号")
        return raw

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    _restrict_permissions(path)
    return key


def _restrict_permissions(path: Path) -> None:
    """best-effort 收紧权限。Windows 上 chmod 只影响只读位，不构成权限隔离。"""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    return Fernet(key).encrypt(data)


def decrypt_bytes(token: bytes, key: bytes) -> bytes:
    try:
        return Fernet(key).decrypt(token)
    except (InvalidToken, ValueError, TypeError) as e:
        # ValueError/TypeError 覆盖「密钥本身不是合法 Fernet key」的情况
        raise AccountsDecryptError("账号密文无法解密：密钥不匹配或文件已损坏") from e
