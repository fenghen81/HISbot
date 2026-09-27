"""配置页、作业管理页、数据查看页、审计页（文档 6.3 / F-01/F-17/F-18）。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import csv

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...audit import verify_chain


def _table(headers, rows):
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            t.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
    t.resizeColumnsToContents()
    return t


# ====================================================================== #
# 配置页
# ====================================================================== #
class AuditView(QWidget):
    def __init__(self, container, parent=None):
        super().__init__(parent)
        self.c = container
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.level = QComboBox()
        self.level.addItems(["全部级别", "INFO", "WARN", "ERROR"])
        q = QPushButton("查询")
        q.clicked.connect(self.load)
        report = QPushButton("导出审计报告并校验日志链")
        report.clicked.connect(self.export_report)
        self.chain_lab = QLabel()
        bar.addWidget(self.level); bar.addWidget(q); bar.addStretch(1)
        bar.addWidget(self.chain_lab); bar.addWidget(report)
        lay.addLayout(bar)
        self.tabs = QTabWidget()
        self.log_t = _table([], [])
        self.alert_t = _table([], [])
        self.audit_t = _table([], [])
        self.tabs.addTab(self.log_t, "操作日志")
        self.tabs.addTab(self.alert_t, "告警（双击确认）")
        self.tabs.addTab(self.audit_t, "访问审计")
        self.tabs.currentChanged.connect(lambda _: self.load())
        lay.addWidget(self.tabs)
        self.alert_t.cellDoubleClicked.connect(self._ack)
        self.load()

    def load(self):
        idx = self.tabs.currentIndex()
        if idx == 0:
            lv = self.level.currentText()
            sql = ("SELECT ts,level,state,action,target_desc,result,"
                   "error_code,snapshot_path FROM t_operation_log")
            params = []
            if lv != "全部级别":
                sql += " WHERE level=?"; params.append(lv)
            sql += " ORDER BY id DESC LIMIT 1000"
            rows = [tuple(r) for r in self.c.db.execute(sql, params)]
            self._set(self.log_t, ["时间", "级别", "阶段", "动作", "目标",
                                   "结果", "错误码", "快照"], rows)
        elif idx == 1:
            rows = [tuple(r) for r in self.c.db.execute(
                "SELECT id,ts,severity,error_code,message,acknowledged "
                "FROM t_alert ORDER BY id DESC LIMIT 500")]
            self._set(self.alert_t, ["ID", "时间", "级别", "错误码",
                                     "信息", "已确认"], rows)
        else:
            rows = [tuple(r) for r in self.c.db.execute(
                "SELECT ts,actor,event_type,object_type,object_id,detail,"
                "result FROM t_audit_event ORDER BY id DESC LIMIT 1000")]
            self._set(self.audit_t, ["时间", "操作人", "事件", "对象类型",
                                     "对象", "明细", "结果"], rows)

    def _set(self, old, headers, rows):
        nt = _table(headers, rows)
        idx = self.tabs.indexOf(old)
        title = self.tabs.tabText(idx)
        self.tabs.removeTab(idx)
        self.tabs.insertTab(idx, nt, title)
        self.tabs.setCurrentIndex(idx)
        if old is self.log_t:
            self.log_t = nt
        elif old is self.alert_t:
            self.alert_t = nt
            nt.cellDoubleClicked.connect(self._ack)
        else:
            self.audit_t = nt

    def _ack(self, r, _c):
        try:
            aid = int(self.alert_t.item(r, 0).text())
            self.c.alerts.ack(aid)
            self.load()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出审计报告",
                                              "audit_report.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        ok, _line, msg = verify_chain(self.c.logger.path or "")
        rows = self.c.db.execute(
            "SELECT ts,level,state,action,target_desc,result,error_code "
            "FROM t_operation_log ORDER BY id").fetchall()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["#日志哈希链校验", "通过" if ok else "失败", msg])
            w.writerow(["时间", "级别", "阶段", "动作", "目标", "结果",
                        "错误码"])
            for r in rows:
                w.writerow(tuple(r))
        self.c.repo.audit("operator", "audit_export",
                          object_type="csv", object_id=path,
                          detail=f"导出审计报告，哈希链{'通过' if ok else '失败'}")
        self.chain_lab.setText(
            f"<span style:color={'green' if ok else 'red'}>"
            f"日志链：{'完整' if ok else '异常'}</span>")
        QMessageBox.information(self, "审计报告",
                                f"已导出：{path}\n哈希链校验：{msg}")
