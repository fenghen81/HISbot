"""落盘稳定态检测（文档 4.6.1 信号 B）。

- 文件大小连续 N 次采样不变（间隔 ≥500ms）；
- 以独占方式尝试打开成功（写句柄已释放）；
- 文件头魔数与扩展名一致。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import os
import sys


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def try_exclusive_open(path: str) -> bool:
    """尝试以写方式打开并获取非排他锁；失败说明可能仍被写入进程占用。"""
    try:
        f = open(path, "r+b")
    except OSError:
        return False
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                return True
            except OSError:
                return False
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return True
            except OSError:
                return False
    finally:
        try:
            f.close()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
