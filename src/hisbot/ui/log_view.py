"""运行日志组件（文档 6.2 运行日志表 / F-12）。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_COLS = ["时间", "级别", "页面", "动作", "目标", "结果", "编码/说明"]
_MAX = 5000


class LogView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(["全部", "INFO", "WARN", "ERROR"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索日志…")
        clear = QPushButton("清空")
        bar.addWidget(self.filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(clear)
        lay.addLayout(bar)
        self.tbl = QTableWidget(0, len(_COLS))
        self.tbl.setHorizontalHeaderLabels(_COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setStyleSheet(
            "QTableWidget{font-family:Menlo,Consolas,monospace;"
            "font-size:12px;}")
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        lay.addWidget(self.tbl)
        self._rows: list[dict] = []
        self.filter.currentTextChanged.connect(self._refresh)
        self.search.textChanged.connect(self._refresh)
        clear.clicked.connect(self.clear)

    def append(self, rec: dict):
        row = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "level": rec.get("level", "INFO"),
            "state": rec.get("state", ""),
            "action": rec.get("action", ""),
            "target": rec.get("target", ""),
            "result": rec.get("result", ""),
            "msg": rec.get("message", "") or
                   (f"{rec.get('code','')} ").strip(),
        }
        self._rows.append(row)
        if len(self._rows) > _MAX:
            self._rows = self._rows[-_MAX:]
        if self._visible(row):
            self._add_row(row)

    def clear(self):
        self._rows.clear()
        self.tbl.setRowCount(0)

    def _visible(self, row):
        lvl = self.filter.currentText()
        if lvl != "全部" and row["level"] != lvl:
            return False
        q = self.search.text().strip()
        if q and q not in " ".join(str(v) for v in row.values()):
            return False
        return True

    def _refresh(self):
        self.tbl.setRowCount(0)
        for row in self._rows:
            if self._visible(row):
                self._add_row(row)

    def _add_row(self, row):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        vals = [row["ts"], row["level"], row["state"], row["action"],
                row["target"], row["result"], row["msg"]]
        for c, v in enumerate(vals):
            item = QTableWidgetItem(str(v))
            if row["level"] == "ERROR":
                item.setForeground(Qt.red)
            elif row["level"] == "WARN":
                item.setForeground(Qt.darkYellow)
            self.tbl.setItem(r, c, item)
        self.tbl.scrollToBottom()
