"""通用工具：时间、目录、线程同步原语。"""
from __future__ import annotations

import datetime as _dt
import os
import threading
from pathlib import Path


def now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级）。"""
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def now_ms() -> int:
    return int(_dt.datetime.now().timestamp() * 1000)


def today_compact() -> str:
    return _dt.date.today().strftime("%Y%m%d")


def ensure_dir(path: str | os.PathLike) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class BooleanFlag:
    """线程安全布尔标志（急停/暂停用，独立标志位，最高优先级）。"""

    def __init__(self, value: bool = False):
        self._ev = threading.Event()
        if value:
            self._ev.set()

    def set(self, value: bool = True) -> None:
        if value:
            self._ev.set()
        else:
            self._ev.clear()

    def get(self) -> bool:
        return self._ev.is_set()

    def wait(self, timeout: float) -> bool:
        """返回 True 表示标志被置位。"""
        return self._ev.wait(timeout)

    def __bool__(self) -> bool:
        return self._ev.is_set()
