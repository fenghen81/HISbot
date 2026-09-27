"""看门狗（文档表 14 SYS-002）：监控执行线程心跳，超时无心跳判定卡死并中止。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import threading
import time
from collections.abc import Callable


class Watchdog:
    def __init__(self, timeout_s: int = 180, check_s: int = 10,
                 on_timeout: Callable[[], None] | None = None,
                 logger=None):
        self.timeout_s = timeout_s
        self.check_s = check_s
        self.on_timeout = on_timeout
        self.logger = logger
        self._last = time.time()
        self._stop = threading.Event()
        self._fired = False
        self._thr: threading.Thread | None = None

    def beat(self):
        self._last = time.time()

    def start(self):
        self._last = time.time()
        self._fired = False
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True,
                                     name="watchdog")
        self._thr.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.check_s):
            gap = time.time() - self._last
            if gap > self.timeout_s and not self._fired:
                self._fired = True
                if self.logger is not None:
                    try:
                        self.logger.error(
                            f"执行线程 {int(gap)}s 无心跳，判定卡死 SYS-002",
                            "SYS-002")
                    except Exception:
                        _log.warning("忽略异常 @%s", __name__, exc_info=True)
                if self.on_timeout is not None:
                    try:
                        self.on_timeout()
                    except Exception:
                        _log.warning("忽略异常 @%s", __name__, exc_info=True)
                return
