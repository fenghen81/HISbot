"""轻量线程安全事件总线。

工作线程（扫描/执行/下载/解析）通过事件总线广播消息，
展现层订阅后用 Qt 信号转发到主线程；业务内核不依赖 GUI。
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

_log = logging.getLogger("hisbot")


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Callable[..., None]]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, event: str, cb: Callable[..., None]) -> Callable[[], None]:
        with self._lock:
            self._subs[event].append(cb)

        def _off():
            with self._lock:
                if cb in self._subs[event]:
                    self._subs[event].remove(cb)
        return _off

    def emit(self, event: str, **payload: Any) -> None:
        with self._lock:
            cbs = list(self._subs.get(event, ()))
        for cb in cbs:
            try:
                cb(**payload)
            except Exception:  # 订阅者异常不影响内核
                _log.warning("事件订阅者处理 %s 时抛错", event, exc_info=True)

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()


# 全局事件名集中声明，避免魔法字符串
EVT_LOG = "log"                 # 结构化日志
EVT_FRAME = "frame"             # 屏幕镜像帧 + overlay
EVT_STATE = "state"             # 状态机变化
EVT_PROGRESS = "progress"       # 进度
EVT_ALERT = "alert"             # 告警
EVT_SCAN = "scan"               # 扫描进度
EVT_TOAST = "toast"             # 简短提示
