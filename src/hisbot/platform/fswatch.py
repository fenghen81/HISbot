"""跨平台文件系统监听（watchdog）。

watchdog 在 Linux 走 inotify、Windows 走 ReadDirectoryChangesW，
符合文档"文件系统事件为主、定时轮询为辅"（轮询兜底在下载子系统内实现）。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..core.types import FsEvent, FsEventType, Handle
from .base import FsWatcher


class _Handler(FileSystemEventHandler):
    def __init__(self, cb: Callable[[FsEvent], None]):
        self.cb = cb

    def _emit(self, etype: FsEventType, path: str):
        self.cb(FsEvent(etype, path, time.time()))

    def on_created(self, e):
        self._emit(FsEventType.CREATED, e.src_path)

    def on_modified(self, e):
        self._emit(FsEventType.MODIFIED, e.src_path)

    def on_moved(self, e):
        self._emit(FsEventType.MOVED, e.dest_path)

    def on_deleted(self, e):
        self._emit(FsEventType.DELETED, e.src_path)


class WatchdogWatcher(FsWatcher):
    def __init__(self):
        self._lock = threading.RLock()
        self._seq = 0

    def watch(self, path: str, cb: Callable[[FsEvent], None]) -> Handle:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        obs = Observer()
        watch = obs.schedule(_Handler(cb), str(p), recursive=False)
        obs.daemon = True
        obs.start()
        with self._lock:
            self._seq += 1
            return {"id": self._seq, "observer": obs, "watch": watch}

    def stop(self, handle: Handle) -> None:
        if not handle:
            return
        obs = handle.get("observer")
        if obs:
            try:
                obs.unschedule(handle.get("watch"))
                obs.stop()
                obs.join(timeout=2)
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
