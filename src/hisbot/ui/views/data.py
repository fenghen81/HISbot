"""配置页、作业管理页、数据查看页、审计页（文档 6.3 / F-01/F-17/F-18）。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import csv

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


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
class DataView(QWidget):
    def __init__(self, container, parent=None):
        super().__init__(parent)
        self.c = container
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.date = QLineEdit(); self.date.setPlaceholderText("报表日期")
        self.dept = QLineEdit(); self.dept.setPlaceholderText("科室编码")
        q = QPushButton("查询")
        q.clicked.connect(self.load)
        export = QPushButton("导出结果(CSV)")
        export.clicked.connect(self.export_csv)
        bar.addWidget(self.date); bar.addWidget(self.dept)
        bar.addWidget(q); bar.addStretch(1); bar.addWidget(export)
        lay.addLayout(bar)
        self.tabs = QTabWidget()
        self.rec = _table([], [])
        self.batch = _table([], [])
        self.files = _table([], [])
        self.tabs.addTab(self.rec, "入库记录(默认脱敏)")
        self.tabs.addTab(self.batch, "批次与质量")
        self.tabs.addTab(self.files, "导出文件血缘")
        lay.addWidget(self.tabs)
        self.load()

    def load(self):
        sql = ("SELECT report_date,dept_code,dept_name,item_code,item_name,"
               "patient_name_mask,id_card_hmac,phone_mask,amount,batch_id,"
               "source_row_no FROM t_report_record WHERE 1=1")
        params = []
        if self.date.text().strip():
            sql += " AND report_date=?"; params.append(self.date.text().strip())
        if self.dept.text().strip():
            sql += " AND dept_code=?"; params.append(self.dept.text().strip())
        sql += " ORDER BY id DESC LIMIT 1000"
        rows = [tuple(r) for r in self.c.db.execute(sql, params).fetchall()]
        self._replace(self.rec, ["日期", "科室码", "科室", "项目码",
                                 "项目", "姓名(脱敏)", "身份证(HMAC)",
                                 "手机(脱敏)", "金额", "批次", "源行"], rows)
        brows = [tuple(r) for r in self.c.db.execute(
            "SELECT b.batch_id,f.origin_name,b.total_rows,b.inserted_rows,"
            "b.updated_rows,b.failed_rows,b.status,p.ok_rows,p.fail_rows,"
            "p.confidence FROM t_import_batch b LEFT JOIN t_export_file f "
            "ON b.file_id=f.file_id LEFT JOIN t_parse_report p "
            "ON p.file_id=b.file_id ORDER BY b.started_at DESC LIMIT 200")]
        self._replace(self.batch, ["批次", "文件", "总行", "插入", "更新",
                                   "失败", "状态", "解析OK", "解析失败",
                                   "置信度"], brows)
        frows = [tuple(r) for r in self.c.db.execute(
            "SELECT origin_name,archived_path,file_size,signal_prompt,"
            "signal_stable,sha256,parse_status,download_finished_at "
            "FROM t_export_file ORDER BY rowid DESC LIMIT 200")]
        self._replace(self.files, ["原始名", "归档路径", "大小", "信号A",
                                   "信号B", "SHA256", "解析状态", "完成时间"],
                      frows)

    def _replace(self, old, headers, rows):
        nt = _table(headers, rows)
        self.tabs.removeTab(self.tabs.indexOf(old))
        idx = self.tabs.addTab(nt, old.windowTitle() or "数据")
        self.tabs.setCurrentIndex(idx)
        if old is self.rec:
            self.rec = nt
        elif old is self.batch:
            self.batch = nt
        else:
            self.files = nt

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出结果(脱敏)",
                                              "report_export.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        t = self.tabs.currentWidget()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([t.horizontalHeaderItem(i).text()
                        for i in range(t.columnCount())])
            for r in range(t.rowCount()):
                w.writerow([t.item(r, c).text()
                            for c in range(t.columnCount())])
        self.c.repo.audit("operator", "result_export",
                          object_type="csv", object_id=path,
                          detail="导出脱敏查询结果")
        QMessageBox.information(self, "已导出", path)


# ====================================================================== #
# 审计页
# ====================================================================== #
