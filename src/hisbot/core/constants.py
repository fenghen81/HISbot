"""跨模块共享常量。"""
from __future__ import annotations

# 浏览器下载临时后缀（文档 4.6.1）
TEMP_SUFFIXES = (".crdownload", ".part", ".tmp", ".download", ".!ut")

# 允许解析/下载的扩展名
ALLOWED_EXPORT_EXT = (".xlsx", ".xls", ".csv", ".pdf")

# 文件头魔数（文档 4.6.1：xlsx→PK，pdf→%PDF）
FILE_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".xlsx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),  # ZIP 容器
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),          # OLE2 复合文档
    ".pdf": (b"%PDF-",),
    # csv 为纯文本，魔数通过可打印性 + BOM 校验
    ".csv": (),
}

# 文本类编码 BOM
BOMS = {
    "utf-8-sig": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
}

# 状态色（文档第 6 章）
COLOR_PRIMARY = "#1F4E79"
COLOR_DANGER = "#E03131"
COLOR_SUCCESS = "#2F9E44"
COLOR_WARN = "#F08C00"
