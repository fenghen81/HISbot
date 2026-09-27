"""执行操作员：把“窗口客户区坐标”的感知结果转为人类化的系统输入。

感知 / 定位全程使用窗口客户区像素坐标（与元素 rel_bbox 同坐标系）；
真正注入时按窗口在屏幕上的外接矩形平移为屏幕绝对坐标。
测试可用 FakeOperator 注入，端到端用 HumanOperator 驱动真实平台。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

from ..core.types import Rect
from .human import HumanSim


class HumanOperator:
    def __init__(self, capturer, injector, human: HumanSim, hwid: str,
                 back_keys=("alt", "Left")):
        self.capturer = capturer
        self.injector = injector
        self.human = human
        self.hwid = hwid
        self.back_keys = back_keys
        self._off = (0, 0)

    def capture(self):
        if self.hwid == "root":
            # 未绑定具体窗口：全屏捕获，坐标原点即屏幕原点
            frame = self.capturer.capture(None)
            w, h = self.capturer.screen_size()
            self._off = (0, 0)
            self._root_rect = Rect(0, 0, w, h)
            return frame.image
        frame, rect = self.capturer.capture_window(self.hwid)
        self._off = (rect.x, rect.y)
        return frame.image

    def focus(self) -> bool:
        if self.hwid == "root":
            return True
        return self.capturer.focus_window(self.hwid)

    def _to_screen(self, rect: Rect) -> Rect:
        ox, oy = self._off
        return Rect(rect.x + ox, rect.y + oy, rect.w, rect.h)

    def click_rect(self, rect: Rect):
        return self.human.click_in_rect(self._to_screen(rect))

    def click_point(self, x: int, y: int):
        self.human.click_point(x + self._off[0], y + self._off[1])

    def type_text(self, text: str):
        self.human.type_text(text)

    def hotkey(self, *keys):
        self.human.hotkey(*keys)

    def back(self):
        self.human.hotkey(*self.back_keys)

    def release_all(self):
        try:
            self.injector.release_all()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
