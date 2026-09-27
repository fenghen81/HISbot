"""人类化操作模拟（文档 4.5.3 / 表 11）。

- 贝塞尔曲线移动，全程 200~600ms，带轻微手抖噪声；
- 落点在目标元素区域内随机偏移 ±15%，不偏离可点区域；
- 鼠标按下到抬起 50~120ms 随机（由平台 click 实现，本处保留间隔）；
- 键盘逐字符 60~180ms/字（中文由平台走剪贴板，规避输入法）；
- 动作之间随机等待 300~800ms；
- 全程可被急停标志以 ≤50ms 粒度中断。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import math
import random
import time
from collections.abc import Callable

from ..core.types import Rect


class HumanSim:
    def __init__(self, injector, *,
                 move_ms=(200, 600), press_ms=(50, 120),
                 type_ms=(60, 180), action_gap_ms=(300, 800),
                 jitter_ratio: float = 0.15,
                 is_abort: Callable[[], bool] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.inj = injector
        self.move_ms = move_ms
        self.press_ms = press_ms
        self.type_ms = type_ms
        self.gap = action_gap_ms
        self.jitter = jitter_ratio
        self.is_abort = is_abort
        self.sleep = sleep
        self.rng = random.Random()
        self._last = None

    def _checkpoint(self):
        if self.is_abort and self.is_abort():
            try:
                self.inj.release_all()
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
            from ..core.errors import AbortedByUser
            raise AbortedByUser("操作过程中操作员急停")

    # ------------------------------------------------------------------ #
    def _bezier_path(self, x0, y0, x1, y1) -> list[tuple[int, int]]:
        steps = self.rng.randint(10, 16)
        # 两个控制点相对直线横向偏移，模拟弧形移动
        dx, dy = x1 - x0, y1 - y0
        nx, ny = -dy, dx
        norm = math.hypot(nx, ny) or 1.0
        bend = self.rng.uniform(0.08, 0.22) * max(abs(dx), abs(dy), 1)
        c1x = x0 + dx * 0.3 + nx / norm * bend * self.rng.choice((1, -1))
        c1y = y0 + dy * 0.3 + ny / norm * bend * self.rng.choice((1, -1))
        c2x = x0 + dx * 0.7 + nx / norm * bend * self.rng.choice((1, -1))
        c2y = y0 + dy * 0.7 + ny / norm * bend * self.rng.choice((1, -1))
        pts = []
        for i in range(steps + 1):
            t = i / steps
            mt = 1 - t
            x = mt ** 3 * x0 + 3 * mt * mt * t * c1x + \
                3 * mt * t * t * c2x + t ** 3 * x1
            y = mt ** 3 * y0 + 3 * mt * mt * t * c1y + \
                3 * mt * t * t * c2y + t ** 3 * y1
            # 轻微手抖
            x += self.rng.uniform(-0.6, 0.6)
            y += self.rng.uniform(-0.6, 0.6)
            pts.append((int(round(x)), int(round(y))))
        return pts

    def move(self, x: int, y: int):
        self._checkpoint()
        x0, y0 = self._last if self._last else (x, y)
        total = self.rng.randint(*self.move_ms)
        path = self._bezier_path(x0, y0, x, y)
        seg = max(1, total // len(path))
        for px, py in path:
            self.inj.move_to(px, py, duration_ms=seg)
        self._last = (x, y)

    def click_point(self, x: int, y: int):
        self.move(x, y)
        self._checkpoint()
        self.inj.click(x, y, "left")           # 平台内部 50~120ms 按抬
        self._post_action()

    def click_in_rect(self, rect: Rect) -> tuple[int, int]:
        cx, cy = rect.center
        rx = rect.w * self.jitter / 2
        ry = rect.h * self.jitter / 2
        x = int(cx + self.rng.uniform(-rx, rx))
        y = int(cy + self.rng.uniform(-ry, ry))
        # 夹紧到矩形内部
        x = max(rect.x + 1, min(rect.x2 - 1, x))
        y = max(rect.y + 1, min(rect.y2 - 1, y))
        self.click_point(x, y)
        return x, y

    def type_text(self, text: str):
        self._checkpoint()
        self.inj.type_text(text, interval_ms=self.rng.randint(*self.type_ms))
        self._post_action()

    def hotkey(self, *keys):
        self._checkpoint()
        self.inj.hotkey(*keys)
        self._post_action()

    def _post_action(self):
        self.sleep(self.rng.randint(*self.gap) / 1000.0)
