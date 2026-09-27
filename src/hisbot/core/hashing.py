"""哈希与感知哈希工具。

- SHA-256：文件完整性 / 归档 / 配置指纹
- 感知哈希（pHash，DCT）：页面整体相似度、元素区域指纹
- HMAC：敏感字段精确检索索引（如身份证）
"""
from __future__ import annotations

import hashlib
import hmac

import numpy as np


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def hmac_index(key: bytes, value: str) -> str:
    """敏感字段（身份证等）的确定性 HMAC 索引，用于精确匹配且不明文落盘。"""
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _dct_1d(n: int) -> np.ndarray:
    """正交 DCT-II 基矩阵（避免依赖 scipy）。"""
    mat = np.zeros((n, n), dtype=np.float64)
    for k in range(n):
        alpha = np.sqrt(1.0 / n) if k == 0 else np.sqrt(2.0 / n)
        for i in range(n):
            mat[k, i] = alpha * np.cos(np.pi * k * (2 * i + 1) / (2 * n))
    return mat


# 32x32 的 DCT 基矩阵（模块级缓存）
_DCT32 = _dct_1d(32)


def phash(gray: np.ndarray, hash_size: int = 16,
          highfreq_factor: int = 2) -> int:
    """DCT 感知哈希，返回 256bit 整数。gray 为灰度图。

    纯 NumPy 实现，避免 scipy 依赖；对缩放/轻微失真鲁棒。
    """
    import cv2
    img_size = hash_size * highfreq_factor  # 32
    resized = cv2.resize(gray, (img_size, img_size),
                         interpolation=cv2.INTER_AREA)
    resized = resized.astype(np.float32)
    dct = _DCT32 @ resized @ _DCT32.T
    low = dct[:hash_size, :hash_size]
    med = np.median(low[1:].flatten())  # 排除 DC 分量
    bits = (low > med).flatten()
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def phash_hex(gray: np.ndarray) -> str:
    return f"{phash(gray):064x}"


def hamming_hex(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def phash_similarity(a: str, b: str) -> float:
    """两个 256bit phash 的相似度，1.0 完全相同。"""
    if not a or not b:
        return 0.0
    bits = max(len(a), len(b)) * 4
    return 1.0 - hamming_hex(a, b) / bits


def hamming_int_similarity(a: int, b: int, bits: int = 256) -> float:
    return 1.0 - bin(a ^ b).count("1") / bits
