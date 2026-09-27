"""归档：落盘确认后重命名移入归档目录（文档 4.6.4）。

命名 {作业名}_{业务日期}_{序号}.ext，序号自增不覆盖；
同盘 rename 原子移动，跨盘复制+校验+删除；移动失败回退并告警 DLD-006。
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass

from ..core.hashing import sha256_file
from ..core.util import ensure_dir


@dataclass
class Archived:
    path: str
    name: str
    size: int
    sha256: str


def _same_fs(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def next_seq(directory, base: str, ext: str) -> int:
    """扫描归档目录，返回下一个可用 3 位序号（同名重复自增，不覆盖）。"""
    seq = 1
    if not os.path.isdir(directory):
        return seq
    pat = re.compile(rf"^{re.escape(base)}_(\d{{3}}){re.escape(ext)}$")
    for name in os.listdir(directory):
        m = pat.match(name)
        if m:
            seq = max(seq, int(m.group(1)) + 1)
    return seq


def archive_file(src: str, archive_root: str, job_name: str,
                 biz_date: str, ext: str | None = None) -> Archived:
    ext = ext if ext is not None else os.path.splitext(src)[1]
    ext = ext.lower()
    directory = ensure_dir(os.path.join(archive_root, job_name, biz_date))
    base = f"{job_name}_{biz_date}"
    for _ in range(1000):
        seq = next_seq(directory, base, ext)
        target_name = f"{base}_{seq:03d}{ext}"
        target = os.path.join(directory, target_name)
        if not os.path.exists(target):
            break
    else:
        raise RuntimeError("归档序号溢出")

    digest = sha256_file(src)
    size = os.path.getsize(src)
    try:
        ensure_dir(os.path.dirname(target))
        if _same_fs(src, str(directory)):
            os.replace(src, target)       # 同盘原子重命名
        else:
            shutil.copy2(src, target)
            if os.path.getsize(target) != size or \
                    sha256_file(target) != digest:
                os.remove(target)
                raise OSError("跨盘复制校验失败")
            os.remove(src)
        return Archived(target, target_name, size, digest)
    except Exception:
        # 回退：文件留在下载目录，由上层告警 DLD-006
        raise
