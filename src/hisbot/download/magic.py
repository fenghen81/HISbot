"""文件头魔数校验（文档 4.6.1：xlsx→PK，pdf→%PDF）。

校验真实文件头与扩展名一致，防止伪装文件进入解析；CSV 为纯文本，
按可解码性与无 NUL 字节校验。
"""
from __future__ import annotations

from ..core.constants import FILE_MAGIC


def read_head(path: str, n: int = 8) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def check_magic(path: str, ext: str) -> bool:
    ext = ext.lower()
    magics = FILE_MAGIC.get(ext)
    try:
        head = read_head(path, 8)
    except Exception:
        return False
    if ext == ".csv":
        return _looks_like_text(path)
    if not magics:
        # 未登记魔数的类型不做强校验（白名单已限制扩展名）
        return True
    return any(head.startswith(m) for m in magics)


def _looks_like_text(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            raw = f.read(4096)
    except Exception:
        return False
    if b"\x00" in raw:
        return False
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            raw.decode(enc)
            return True
        except Exception:
            continue
    return False


def detect_ext_by_magic(path: str) -> str | None:
    """根据文件头反推扩展名（辅助诊断）。"""
    head = read_head(path)
    if head.startswith(b"PK\x03\x04"):
        return ".xlsx"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return ".xls"
    if head.startswith(b"%PDF-"):
        return ".pdf"
    if _looks_like_text(path):
        return ".csv"
    return None
