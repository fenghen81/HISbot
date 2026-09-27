"""配置页、作业管理页、数据查看页、审计页（文档 6.3 / F-01/F-17/F-18）。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")


from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
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
class JobsView(QWidget):
    def __init__(self, container, on_run, on_scan, parent=None):
        super().__init__(parent)
        self.c = container
        self.on_run = on_run
        self.on_scan = on_scan
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.sim = QCheckBox("仿真模式（无真实 HIS 时勾选）")
        self.sim.setChecked(True)
        top.addWidget(self.sim)
        top.addStretch(1)
        scan = QPushButton("只读扫描生成导航图")
        scan.clicked.connect(lambda: self.on_scan(self.sim.isChecked()))
        top.addWidget(scan)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.load)
        top.addWidget(refresh)
        lay.addLayout(top)

        self.listw = QListWidget()
        lay.addWidget(QLabel("已签发作业（config/jobs）："))
        lay.addWidget(self.listw)

        btns = QHBoxLayout()
        run = QPushButton("立即执行")
        run.setStyleSheet("background:#1F4E79;color:white;padding:6px;")
        run.clicked.connect(self._run)
        btns.addWidget(run)
        self.sched_btn = QPushButton("加入/移出定时调度")
        self.sched_btn.clicked.connect(self._toggle_sched)
        btns.addWidget(self.sched_btn)
        lay.addLayout(btns)

        lay.addWidget(QLabel("最近运行历史："))
        self.runs = _table(["run_id", "job", "开始", "状态", "阶段",
                            "文件", "行数", "错误码"], [])
        lay.addWidget(self.runs, 1)
        self.load()

    def load(self):
        self.listw.clear()
        for p in self.c.center.list_jobs():
            self.listw.addItem(p.name)
        rows = self.c.db.execute(
            "SELECT run_id,job_id,started_at,status,current_state,"
            "files_downloaded,rows_imported,error_code FROM t_job_run "
            "ORDER BY started_at DESC LIMIT 50").fetchall()
        lay = self.runs
        self.runs = _table(["run_id", "job", "开始", "状态", "阶段",
                            "文件", "行数", "错误码"],
                           [tuple(r) for r in rows])
        parent = lay.parent()
        lay.setParent(None)
        parent.layout().replaceWidget(lay, self.runs) if hasattr(
            parent, "layout") else None

    def _selected(self):
        it = self.listw.currentItem()
        return it.text() if it else None

    def _run(self):
        name = self._selected()
        if not name:
            QMessageBox.information(self, "提示", "请选择一个作业。")
            return
        self.on_run(name, self.sim.isChecked())

    def _toggle_sched(self):
        name = self._selected()
        if not name:
            return
        cfg = self.c.center.load_job(name)
        job = cfg.get("job", cfg)
        jid = job["job_id"]
        if jid in self.c.scheduler.job_ids():
            self.c.scheduler.unregister(jid)
            QMessageBox.information(self, "调度", f"已移出定时调度：{jid}")
        else:
            try:
                self.c.scheduler.register(cfg)
                QMessageBox.information(
                    self, "调度",
                    f"已加入定时调度：{job.get('schedule', {}).get('cron')}")
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "调度失败", str(e))


# ====================================================================== #
# 数据查看页（默认脱敏展示）
# ====================================================================== #
