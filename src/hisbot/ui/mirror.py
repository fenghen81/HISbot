"""实时镜像组件（文档 6.2 / F-12）。

定时抓取操作员画面（仅截图，不做 OCR，避免与执行线程争抢算力），
叠加待点击元素红色高亮框与已完成元素淡绿框；镜像区不可被遮挡。
"""
from __future__ import annotations

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

RED = QColor("#E03131")
GREEN = QColor("#2F9E44")
BLUE = QColor("#1F4E79")


class MirrorView(QWidget):
    def __init__(self, fps: int = 5, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 420)
        self.setStyleSheet("background:#101418;")
        self._pix: QPixmap | None = None
        self._operator = None
        self._hint = None                 # (text,(x,y,w,h),state)
        self._done: list[tuple] = []
        self._info_line = "就绪"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(max(100, int(1000 / max(1, fps))))

    def set_operator(self, op):
        self._operator = op
        self._done.clear()
        self._hint = None

    def clear_operator(self):
        self._operator = None
        self._pix = None
        self._hint = None
        self.update()

    def set_hint(self, text, rect, state):
        if self._hint is not None:
            self._done.append((self._hint[1], self._fw, self._fh))
            self._done = self._done[-20:]
        self._hint = (text, tuple(rect), state)
        self._fw, self._fh = (self._fwh if hasattr(self, "_fwh")
                              else (1, 1))

    def set_info(self, text: str):
        self._info_line = text

    # ------------------------------------------------------------------ #
    def _tick(self):
        if self._operator is None:
            return
        try:
            frame = self._operator.capture()
        except Exception:
            return
        if frame is None:
            return
        self._fwh = (frame.shape[1], frame.shape[0])
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(img)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101418"))
        if not self._pix:
            p.setPen(QColor("#868E96"))
            p.setFont(QFont("", 14))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "实时镜像区（启动作业后显示 HIS 画面）")
            self._draw_info(p)
            return
        # 等比缩放居中
        pw, ph = self._pix.width(), self._pix.height()
        scale = min(self.width() / pw, (self.height() - 34) / ph)
        dw, dh = int(pw * scale), int(ph * scale)
        ox, oy = (self.width() - dw) // 2, (self.height() - 34 - dh) // 2
        p.drawPixmap(ox, oy, dw, dh, self._pix)

        def map_rect(r):
            x, y, w, h = r
            return (ox + int(x / pw * dw), oy + int(y / ph * dh),
                    max(2, int(w / pw * dw)), max(2, int(h / ph * dh)))

        for r, fw, fh in self._done:
            rx, ry, rw, rh = self._scaled(r, fw, fh, ox, oy, dw, dh)
            pen = QPen(GREEN, 2)
            p.setPen(pen)
            p.drawRect(rx, ry, rw, rh)
        if self._hint:
            fw = getattr(self, "_fwh", (pw, ph))[0]
            fh = getattr(self, "_fwh", (pw, ph))[1]
            rx, ry, rw, rh = self._scaled(self._hint[1], fw, fh,
                                          ox, oy, dw, dh)
            pen = QPen(RED, 3)
            p.setPen(pen)
            p.drawRect(rx, ry, rw, rh)
            p.fillRect(rx, max(0, ry - 22),
                       min(rw + 160, 150), 22, RED)
            p.setPen(QColor("white"))
            p.setFont(QFont("", 9))
            p.drawText(rx + 4, ry - 6,
                       f"{self._hint[0]} ◀ {self._hint[2]}")
        self._draw_info(p)

    def _scaled(self, r, fw, fh, ox, oy, dw, dh):
        x, y, w, h = r
        fw = fw or 1
        fh = fh or 1
        return (ox + int(x / fw * dw), oy + int(y / fh * dh),
                max(2, int(w / fw * dw)), max(2, int(h / fh * dh)))

    def _draw_info(self, p):
        p.fillRect(0, self.height() - 30, self.width(), 30, BLUE)
        p.setPen(QColor("white"))
        p.setFont(QFont("", 10))
        p.drawText(10, self.height() - 10, self._info_line)
