"""可独立启动的仿真 HIS 桌面窗口（真实 PySide6 控件）。

用途：在没有真实 HIS 的环境里，让虚拟操作员通过 XTest 对真实窗口做
端到端演示与 GUI 冒烟。启动：
    python -m hisbot.simulator.app --watch ./data/downloads
窗口固定在屏幕左上角、1000x680，控件使用绝对定位以便 OCR/XTest 命中。
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMainWindow, QPushButton, QWidget

from .reportgen import write_report_xlsx


class _Bridge(QObject):
    download_done = Signal(str)


class SimHisWindow(QMainWindow):
    W, H = 1000, 680

    def __init__(self, watch_dir: str, file_name: str = "住院日报.xlsx",
                 write_seconds: float = 0.8):
        super().__init__()
        self.watch_dir = watch_dir
        self.file_name = file_name
        self.write_seconds = write_seconds
        os.makedirs(watch_dir, exist_ok=True)
        self.bridge = _Bridge()
        self.bridge.download_done.connect(self._on_done)
        self.started = False
        self.setWindowTitle("仿真HIS 住院管理系统")
        self.setGeometry(0, 0, self.W, self.H)
        self.setFixedSize(self.W, self.H)
        self._build()

    # ------------------------------------------------------------------ #
    def _title(self, text):
        bar = QWidget(self)
        bar.setGeometry(0, 0, self.W, 46)
        bar.setStyleSheet("background:#1F4E79;")
        lab = QLabel(text, bar)
        lab.setGeometry(20, 8, 600, 30)
        lab.setStyleSheet("color:white;font-size:20px;font-weight:bold;")

    def _btn(self, text, x, y, w=214, h=38, danger=False):
        b = QPushButton(text, self)
        b.setGeometry(x, y, w, h)
        if danger:
            b.setStyleSheet("font-size:18px;color:#AA2828;"
                            "background:#FCF0F0;border:2px solid #AA2828;")
        else:
            b.setStyleSheet("font-size:18px;color:#282828;"
                            "background:#F5F8FB;border:2px solid #788CA0;")
        return b

    def _build(self):
        self._title("HIS 登录")
        # login
        self.user_edit = QLineEdit(self)
        self.user_edit.setGeometry(36, 90, 214, 36)
        self.user_edit.setPlaceholderText("用户名")
        self.pwd_edit = QLineEdit(self)
        self.pwd_edit.setGeometry(36, 154, 214, 36)
        self.pwd_edit.setPlaceholderText("密码")
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.login_btn = self._btn("登录", 36, 218)
        self.login_btn.clicked.connect(self._goto_home)
        # buttons of other pages
        self.btn_report = self._btn("住院报表", 36, 90)
        self.btn_report.clicked.connect(lambda: self._show("rpt"))
        self.btn_daily = self._btn("住院日报", 36, 90)
        self.btn_daily.clicked.connect(lambda: self._show("daily"))
        self.btn_void1 = self._btn("作废", 36, 154, danger=True)
        self.btn_back_r = self._btn("返回", 36, 218)
        self.btn_back_r.clicked.connect(lambda: self._show("home"))
        self.btn_export = self._btn("导出Excel", 36, 90)
        self.btn_export.clicked.connect(self._start_download)
        self.btn_back_d = self._btn("返回", 36, 148)
        self.btn_back_d.clicked.connect(lambda: self._show("rpt"))
        self.btn_void2 = self._btn("作废", 36, 212, danger=True)
        # titles
        self.t_home = QLabel("住院管理系统首页", self)
        self.t_rpt = QLabel("住院报表查询", self)
        self.t_daily = QLabel("住院日报", self)
        for t in (self.t_home, self.t_rpt, self.t_daily):
            t.setGeometry(20, 8, 600, 30)
            t.setStyleSheet("color:white;font-size:20px;font-weight:bold;")
        self.done_lab = QLabel(f"{self.file_name} 下载完成", self)
        self.done_lab.setGeometry(560, self.H - 80, self.W - 580, 40)
        self.done_lab.setStyleSheet("color:#1F783C;font-size:18px;"
                                    "background:#F5F7FA;border:1px solid "
                                    "#BEC8D0;")
        self.done_lab.hide()
        self._pages = {
            "home": [self.btn_report, self.t_home],
            "rpt": [self.btn_daily, self.btn_void1, self.btn_back_r,
                    self.t_rpt],
            "daily": [self.btn_export, self.btn_back_d, self.btn_void2,
                      self.t_daily, self.done_lab],
        }
        self._show("login")

    def _show(self, page):
        login_widgets = [self.user_edit, self.pwd_edit, self.login_btn]
        for w in login_widgets:
            w.setVisible(page == "login")
        for name, ws in self._pages.items():
            for w in ws:
                if w is self.done_lab:
                    continue
                w.setVisible(page == name)
        if page != "daily":
            self.done_lab.hide()

    def _goto_home(self):
        self._show("home")

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
            write_report_xlsx(os.path.join(self.watch_dir, self.file_name))
            os.remove(tmp)
            self.bridge.download_done.emit(self.file_name)

        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, _name):
        self.done_lab.show()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", default="./data/downloads")
    ap.add_argument("--file", default="住院日报.xlsx")
    args = ap.parse_args(argv)
    qt = QApplication.instance() or QApplication(sys.argv)
    win = SimHisWindow(os.path.abspath(args.watch), args.file)
    win.show()
    qt.exec()


if __name__ == "__main__":
    main()
