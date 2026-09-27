# -*- coding: utf-8 -*-
"""在 Xvfb 下启动真实 MainWindow，逐页签导出设计预览 PNG。"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # hisbot/
sys.path.insert(0, os.path.join(ROOT, "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

from hisbot.app.services import Container  # noqa: E402
from hisbot.ui.main_window import MainWindow  # noqa: E402
from hisbot.ui.theme import MODERN_QSS  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(MODERN_QSS)

c = Container(ROOT)
win = MainWindow(c)
win.resize(1320, 840)
win.show()
app.processEvents()
time.sleep(0.6)
app.processEvents()

names = ["monitor", "review", "jobs", "config", "data", "audit"]
outdir = os.path.join(ROOT, "preview")
os.makedirs(outdir, exist_ok=True)
n = win.tabs.count()
for i in range(n):
    win.tabs.setCurrentIndex(i)
    app.processEvents(); time.sleep(0.35); app.processEvents()
    tag = names[i] if i < len(names) else f"tab{i}"
    path = os.path.join(outdir, f"hisbot_{tag}.png")
    win.grab().save(path)
    print("SHOT", path)
print("DONE", n)
