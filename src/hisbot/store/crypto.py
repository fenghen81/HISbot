"""AES-256-GCM 字段级加密与 HMAC 索引（文档 4.8.2 / 7.4）。

密文布局：Base64( nonce[12] || ciphertext || tag[16] )，认证加密防篡改；
密文被改动时解密抛 InvalidTag -> 上层转 DBS-004 并停止上报。
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..core.errors import CipherAuthError, KeyUnavailableError


class CryptoService:
    def __init__(self, master_key_b64: str):
        try:
            key = base64.b64decode(master_key_b64)
            if len(key) != 32:
                raise ValueError("主密钥长度必须为 32 字节（AES-256）")
            self._aes = AESGCM(key)
        except KeyUnavailableError:
            raise
        except Exception as e:
            raise KeyUnavailableError(f"主密钥不可用：{e}") from e
        # 为精确检索索引派生独立 HMAC 密钥（域分离）
        self._hmac_key = hmac.new(
            key, b"hisbot-sensitive-hmac-index-v1", hashlib.sha256).digest()

    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_master_key_b64() -> str:
        import secrets
        return base64.b64encode(secrets.token_bytes(32)).decode("ascii")

    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None or plaintext == "":
            return None
        import os
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str | None) -> str | None:
        if token is None or token == "":
            return None
        try:
            blob = base64.b64decode(token)
            nonce, ct = blob[:12], blob[12:]
            return self._aes.decrypt(nonce, ct, None).decode("utf-8")
        except Exception:
            raise CipherAuthError("密文认证失败，数据可能已被篡改") from None

    def hmac_index(self, value: str | None) -> str | None:
        """敏感字段确定性 HMAC 索引（如身份证精确匹配），不暴露明文。"""
        if value is None or value == "":
            return None
        return hmac.new(self._hmac_key, str(value).encode("utf-8"),
                        hashlib.sha256).hexdigest()
