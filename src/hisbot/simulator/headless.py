"""离屏仿真 HIS（与真实 HumanOperator 同接口），供 pytest / 无显示器联调。

页面流：login → home(住院报表) → rpt(住院日报/作废[危险]) → daily(导出Excel)
点击“导出Excel”后模拟浏览器静默下载：先写 .crdownload 再落 xlsx，
并在窗口底部出现“下载完成”提示（信号 A）。
"""
from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..core.types import Rect
from .reportgen import write_report_xlsx

_FB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
_FR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


class SimHis:
    W, H = 1000, 680

    def __init__(self, watch_dir: str, *, file_name: str = "住院日报.xlsx",
                 report_date: str = "2026-09-22", write_seconds: float = 0.5,
                 include_danger: bool = True, width: int = 1000,
                 height: int = 680, on_event=None, start_page: str = "login"):
        self.watch_dir = watch_dir
        self.file_name = file_name
        self.report_date = report_date
        self.write_seconds = write_seconds
        self.include_danger = include_danger
        self.W, self.H = width, height
        self.on_event = on_event or (lambda e: None)
        self.page = start_page
        self.done = False
        self.started = False
        self.focus = ""
        self.user = ""
        self.pwd = ""
        self._fb = _font(_FB, 22)
        self._fr = _font(_FR, 19)
        os.makedirs(watch_dir, exist_ok=True)

    # --- 与 HumanOperator 一致的接口 --- #
    def frame_extent(self):
        return (self.W, self.H)

    def capture(self):
        layout = self._layout(self.page)
        img = Image.new("RGB", (self.W, self.H), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, self.W, 46], fill=(31, 78, 121))
        d.text((20, 10), layout["title"], font=self._fb, fill=(255, 255, 255))
        for (x1, y1, x2, y2), tx, danger in layout["items"]:
            fill = (252, 240, 240) if danger else (245, 248, 251)
            outline = (170, 40, 40) if danger else (120, 140, 160)
            d.rectangle([x1, y1, x2, y2], outline=outline, width=2,
                        fill=fill)
            d.text((x1 + 14, y1 + 6), tx, font=self._fr,
                   fill=(170, 40, 40) if danger else (40, 40, 40))
        if self.page == "daily" and self.done:
            d.rounded_rectangle([560, self.H - 80, self.W - 20,
                                 self.H - 40], radius=5,
                                fill=(245, 247, 250),
                                outline=(180, 190, 200))
            d.text((572, self.H - 72), f"{self.file_name} 下载完成",
                   font=self._fr, fill=(31, 120, 60))
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    def click_rect(self, rect: Rect):
        x, y = rect.center
        self._hit(x, y)

    def click_point(self, x, y):
        self._hit(x, y)

    def type_text(self, text: str):
        if self.page == "login":
            if self.focus == "pwd":
                self.pwd = text
            else:
                self.user = text
        self.on_event({"type": "type", "text": text})

    def hotkey(self, *keys):
        self.on_event({"type": "hotkey", "keys": keys})

    def back(self):
        self.page = {"rpt": "home", "daily": "rpt"}.get(self.page,
                                                        self.page)
        self.on_event({"type": "back", "page": self.page})

    def release_all(self):
        pass

    # --- 内部 --- #
    def _layout(self, page):
        if page == "login":
            return {"title": "HIS 登录", "items": [
                ((36, 90 - 6, 250, 90 + 30), "用户名", False),
                ((36, 154 - 6, 250, 154 + 30), "密码", False),
                ((36, 218 - 6, 250, 218 + 30), "登录", False)]}
        if page == "home":
            return {"title": "住院管理系统首页", "items": [
                ((36, 84, 250, 120), "住院报表", False)]}
        items = [((36, 84, 250, 120), "住院日报", False)]
        if self.include_danger:
            items.append(((36, 148, 250, 184), "作废", True))
        items.append(((36, 212, 250, 248), "返回", False))
        if page == "rpt":
            return {"title": "住院报表查询", "items": items}
        ditem = [((36, 84, 250, 120), "导出Excel", False),
                 ((36, 148, 250, 184), "返回", False)]
        if self.include_danger:
            ditem.append(((36, 212, 250, 248), "作废", True))
        return {"title": "住院日报", "items": ditem}

    def _hit(self, x, y):
        layout = self._layout(self.page)
        for (x1, y1, x2, y2), tx, _danger in layout["items"]:
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.on_event({"type": "click", "text": tx, "page":
                               self.page})
                if self.page == "login":
                    if tx == "用户名":
                        self.focus = "user"
                    elif tx == "密码":
                        self.focus = "pwd"
                    elif tx == "登录":
                        self.page = "home"
                elif self.page == "home" and tx == "住院报表":
                    self.page = "rpt"
                elif self.page == "rpt" and tx == "住院日报":
                    self.page = "daily"
                elif tx == "返回":
                    self.back()
                elif self.page == "daily" and tx == "导出Excel":
                    self._start_download()
                # “作废”为危险元素：仿真中不产生任何业务动作（只读登记）
                return

    def _start_download(self):
        if self.started:
            return
        self.started = True

        def work():
            tmp = os.path.join(self.watch_dir, self.file_name + ".crdownload")
            with open(tmp, "wb") as f:
                f.write(b"PK" + b"x" * 50000)
                end = time.time() + self.write_seconds
                while time.time() < end:
                    f.write(b"y" * 20000)
                    f.flush()
                    time.sleep(0.05)
            write_report_xlsx(os.path.join(self.watch_dir, self.file_name),
                              self.report_date)
            os.remove(tmp)
            self.done = True
            self.on_event({"type": "download_ready"})

        threading.Thread(target=work, daemon=True).start()
