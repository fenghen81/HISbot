"""导航图审核页（文档 6.3 / F-05）。

加载扫描产出的导航图：选择目标页与导出按钮、自动规划并逐边批准路径、
知悉危险点、选择字段映射后签发作业配置（SHA-256 防篡改）。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..review.service import ReviewError, ReviewService
from ..scan.graph_store import load_graph, save_graph


class ReviewView(QWidget):
    def __init__(self, container, parent=None):
        super().__init__(parent)
        self.c = container
        self.graph = None
        self.steps: list[dict] = []
        root = QHBoxLayout(self)

        # 左：导航树
        left = QVBoxLayout()
        left.addWidget(QLabel("导航图（页面 → 元素）"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["页面 / 元素", "属性"])
        self.tree.itemClicked.connect(self._on_tree)
        left.addWidget(self.tree, 2)
        self.reload_btn = QPushButton("重新加载导航图")
        self.reload_btn.clicked.connect(self.load)
        left.addWidget(self.reload_btn)
        root.addLayout(left, 1)

        # 右
        right = QVBoxLayout()
        self.info = QLabel("页面信息：未加载")
        self.info.setWordWrap(True)
        right.addWidget(self.info)
        self.shot = QLabel("（页面截图）")
        self.shot.setMinimumHeight(150)
        self.shot.setAlignment(Qt.AlignCenter)
        self.shot.setStyleSheet("background:#212529;color:#ADB5BD;")
        right.addWidget(self.shot)

        row = QHBoxLayout()
        row.addWidget(QLabel("目标页:"))
        self.page_combo = QComboBox()
        self.page_combo.currentIndexChanged.connect(self._load_elements)
        row.addWidget(self.page_combo, 1)
        right.addLayout(row)

        self.etbl = QTableWidget(0, 4)
        self.etbl.setHorizontalHeaderLabels(["选择", "文字", "类型", "标记"])
        right.addWidget(self.etbl)
        mark = QPushButton("将勾选元素标注为导出目标")
        mark.clicked.connect(self._mark_export)
        right.addWidget(mark)

        right.addWidget(QLabel("导航路径（逐边批准）："))
        pathrow = QHBoxLayout()
        plan = QPushButton("自动规划最短路径")
        plan.clicked.connect(self._plan)
        pathrow.addWidget(plan)
        pathrow.addWidget(QLabel("映射:"))
        self.map_combo = QComboBox()
        pathrow.addWidget(self.map_combo, 1)
        right.addLayout(pathrow)
        self.path_list = QListWidget()
        right.addWidget(self.path_list, 1)

        rr = QHBoxLayout()
        rr.addWidget(QLabel("审核人:"))
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("业务审核员")
        rr.addWidget(self.reviewer)
        self.ack = QCheckBox("已知悉图中全部危险元素")
        rr.addWidget(self.ack)
        right.addLayout(rr)
        self.sign_btn = QPushButton("审核并签发作业配置")
        self.sign_btn.setStyleSheet("background:#1F4E79;color:white;"
                                    "font-weight:bold;padding:8px;")
        self.sign_btn.clicked.connect(self._submit)
        right.addWidget(self.sign_btn)
        root.addLayout(right, 2)
        self.load()

    # ------------------------------------------------------------------ #
    def load(self):
        path = str(self.c.center.graph_path("v1"))
        self.graph = load_graph(path) if os.path.exists(path) else None
        self.tree.clear()
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.blockSignals(False)
        self.map_combo.clear()
        mdir = os.path.join(self.c.config_dir, "mappings")
        if os.path.isdir(mdir):
            for f in sorted(os.listdir(mdir)):
                if f.endswith((".yaml", ".yml")):
                    self.map_combo.addItem(f"mappings/{f}")
        if self.graph is None:
            self.info.setText("页面信息：未找到导航图，请先在“作业管理”页"
                              "执行只读扫描。")
            return
        for p in self.graph.pages:
            top = QTreeWidgetItem([f"{p.title}（{p.page_id}）",
                                   f"depth {p.depth}"])
            top.setData(0, Qt.UserRole, ("page", p.page_id))
            for e in p.elements:
                tag = ("[危险] " if e.risk == "danger" else "") + \
                      ("[导出] " if e.is_export_target else "") + e.text
                child = QTreeWidgetItem([tag, e.kind])
                child.setData(0, Qt.UserRole, ("element", p.page_id, e.id))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            self.tree.expandItem(top)
            self.page_combo.addItem(f"{p.title}（{p.page_id}）", p.page_id)
        self.info.setText(
            f"页面 {len(self.graph.pages)} 个，边 {len(self.graph.edges)} "
            f"条，危险点 {len(self.graph.dangerous)} 个")

    def _on_tree(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "page":
            idx = self.page_combo.findData(data[1])
            if idx >= 0:
                self.page_combo.setCurrentIndex(idx)

    def _load_elements(self):
        self.etbl.setRowCount(0)
        if self.graph is None:
            return
        pid = self.page_combo.currentData()
        page = self.graph.page(pid) if pid else None
        if not page:
            return
        for e in page.elements:
            r = self.etbl.rowCount()
            self.etbl.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, e.id)
            self.etbl.setItem(r, 0, chk)
            marks = []
            if e.risk == "danger":
                marks.append("危险")
            if e.is_export_target:
                marks.append("导出目标")
            self.etbl.setItem(r, 1, QTableWidgetItem(e.text))
            self.etbl.setItem(r, 2, QTableWidgetItem(e.kind))
            self.etbl.setItem(r, 3, QTableWidgetItem("/".join(marks)))
        snap = page.snapshot
        if snap and os.path.exists(str(snap)):
            self.shot.setPixmap(QPixmap(str(snap)).scaled(
                self.shot.width(), 180, Qt.KeepAspectRatio))
        else:
            self.shot.setText("（该页未保存截图，以指纹与文字为准）")

    def _selected_page(self):
        return self.graph.page(self.page_combo.currentData())

    def _mark_export(self):
        if self.graph is None:
            return
        page = self._selected_page()
        chosen = []
        for r in range(self.etbl.rowCount()):
            item = self.etbl.item(r, 0)
            if item.checkState() == Qt.Checked:
                chosen.append(item.data(Qt.UserRole))
        for e in page.elements:
            if e.id in chosen:
                if e.risk == "danger":
                    QMessageBox.warning(self, "禁止标注",
                                        f"危险元素「{e.text}」不可标注为导出目标")
                    continue
                e.is_export_target = True
        save_graph(self.graph, str(self.c.center.graph_path("v1")))
        self._load_elements()
        QMessageBox.information(self, "已标注", "导出目标已写入导航图。")

    def _plan(self):
        if self.graph is None:
            return
        self.path_list.clear()
        pid = self.page_combo.currentData()
        try:
            self.steps = ReviewService(self.graph).plan_path(pid)
        except ReviewError as e:
            QMessageBox.warning(self, "无法规划", str(e))
            return
        for i, s in enumerate(self.steps, 1):
            it = QListWidgetItem(
                f"{i}. [{s['page_title']}] 点击「{s['text']}」 → "
                f"{s['to_page']}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.path_list.addItem(it)
        if not self.steps:
            self.path_list.addItem("（目标页即起始页，无需导航）")

    def _submit(self):
        if self.graph is None:
            QMessageBox.warning(self, "无导航图", "请先扫描。")
            return
        page = self._selected_page()
        tgt = next((e for e in page.elements if e.is_export_target
                    and e.risk != "danger"), None)
        if tgt is None:
            QMessageBox.warning(self, "缺少导出目标",
                                "请先在目标页勾选并标注导出按钮。")
            return
        approved = []
        for i, s in enumerate(self.steps):
            it = self.path_list.item(i)
            s = dict(s)
            s["approved"] = it.checkState() == Qt.Checked if it else True
            approved.append(s)
        reviewer = self.reviewer.text().strip()
        if not reviewer:
            QMessageBox.warning(self, "缺少审核人", "请填写业务审核员。")
            return
        mapping = self.map_combo.currentText() or None
        template = {
            "job": {
                "job_id": "inpatient_daily_report",
                "job_name": "住院日报导出",
                "site_id": self.c.site.get("site", {}).get("site_id",
                                                            "his-main"),
                "config_version": 0,
                "download": {
                    "expect_files": 1, "expect_name_pattern":
                    r"住院日报.*\.xlsx",
                    "timeout_ms": int(self.c.app.get("timing", {})
                                      .get("download_timeout_ms", 120000)),
                    "on_timeout": "retry", "max_retry": 2},
                "parse": {"mapping": mapping or
                          "mappings/inpatient_daily.yaml",
                          "target_table": "t_report_record"},
                "schedule": {"enabled": False, "cron": "0 8 * * *",
                             "time_window": "08:00-18:00"},
                "safety": {"allow_unapproved_path": False},
                "target": {"button_keywords":
                           list(self.c.kw.get("export_keywords", ["导出"])),
                           "pre_actions": []}}}
        try:
            signed = ReviewService(self.graph).submit(
                template=template, target_page_id=page.page_id,
                target_element_id=tgt.id, steps=approved,
                reviewer=reviewer,
                acknowledge_dangers=self.ack.isChecked(),
                mapping_path=(os.path.join(self.c.config_dir, mapping)
                              if mapping else None))
        except ReviewError as e:
            QMessageBox.critical(self, "签发被拒绝", str(e))
            return
        out = str(self.c.center.save_job("inpatient_daily_report", signed))
        self.c.repo.audit(reviewer, "job_signed", object_type="job",
                          object_id="inpatient_daily_report",
                          detail=f"配置已签发：{out}")
        QMessageBox.information(self, "签发成功",
                                f"作业配置已签名保存：\n{out}")
