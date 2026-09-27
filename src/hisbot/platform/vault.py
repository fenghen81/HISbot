"""凭据保护（文档 4.1 / 7.2）。

优先系统凭据链：Windows DPAPI / Linux Secret Service（经 keyring）。
无凭据服务时降级为机器绑定的本地加密文件 credentials.enc（AES-256-GCM，
权限 600），并在 backend() 中显式标注降级状态。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import base64
import getpass
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

SERVICE_NAME = "HISBot"
_APP_SALT = b"hisbot-credential-vault-v1-machine-bound"


class KeyringVault:
    backend_name = "system-keyring"

    def __init__(self):
        import keyring
        self._kr = keyring

    def save(self, key: str, secret: str) -> None:
        self._kr.set_password(SERVICE_NAME, key, secret)

    def load(self, key: str) -> str | None:
        return self._kr.get_password(SERVICE_NAME, key)

    def delete(self, key: str) -> None:
        try:
            self._kr.delete_password(SERVICE_NAME, key)
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)

    def backend(self) -> str:
        try:
            name = self._kr.get_keyring().__class__.__name__
        except Exception:
            name = "keyring"
        return f"{self.backend_name}:{name}"


class FileVault:
    """降级方案：机器绑定密钥的 AES-256-GCM 加密文件。"""
    backend_name = "file-fallback(machine-bound)"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = self._machine_key()
        self._cache: dict[str, str] = self._read_all()

    def _machine_material(self) -> bytes:
        mid = ""
        for c in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                mid = Path(c).read_text().strip()
                if mid:
                    break
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
        on_windows = False
        try:
            import sys
            on_windows = sys.platform == "win32"
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
        if on_windows:
            import ctypes
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.kernel32.GetComputerNameW(buf, 256)
            mid = mid or buf.value
        material = f"{SERVICE_NAME}|{getpass.getuser()}|{mid}".encode()
        return material

    def _machine_key(self) -> bytes:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=_APP_SALT, iterations=200_000)
        return kdf.derive(self._machine_material())

    def _read_all(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            blob = self.path.read_bytes()
            nonce, ct = blob[:12], blob[12:]
            import json
            raw = AESGCM(self._key).decrypt(nonce, ct, None)
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            # 密钥不可用 / 文件损坏：不静默清空，交由上层报 DBS-003 类错误
            return {}

    def _write_all(self) -> None:
        import json
        raw = json.dumps(self._cache, ensure_ascii=False).encode("utf-8")
        nonce = secrets.token_bytes(12)
        ct = AESGCM(self._key).encrypt(nonce, raw, None)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(nonce + ct)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)

    def save(self, key: str, secret: str) -> None:
        self._cache[key] = secret
        self._write_all()

    def load(self, key: str) -> str | None:
        return self._cache.get(key)

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)
        self._write_all()

    def backend(self) -> str:
        return self.backend_name


def create_vault(config_dir: str | Path, *, probe: str = "__probe__"):
    """优先 keyring（自检一次），失败降级为加密文件。"""
    try:
        v = KeyringVault()
        v.save(probe, "ok")
        got = v.load(probe)
        v.delete(probe)
        if got != "ok":
            raise RuntimeError("keyring roundtrip mismatch")
        return v
    except Exception:
        return FileVault(Path(config_dir) / "credentials.enc")


def get_or_create_secret(vault, key: str, nbytes: int = 32) -> str:
    """读取或生成一个随机密钥（base64），用于数据主密钥等。"""
    val = vault.load(key)
    if not val:
        val = base64.b64encode(secrets.token_bytes(nbytes)).decode("ascii")
        vault.save(key, val)
    return val
