"""主窗口（文档 6.2 / 6.3 / 6.4）：六页选项卡 + 实时监控布局 + 常驻控制。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

from datetime import date, datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .branding import app_icon, resource_path
from .log_view import LogView
from .mirror import MirrorView
from .review_view import ReviewView
from .views import AuditView, ConfigView, DataView, JobsView
from .worker import RunThread, ScanThread

_STATE_CN = {"IDLE": "就绪", "INIT": "初始化", "LOGIN": "登录中",
             "NAVIGATE": "导航中", "TARGET": "定位目标", "EXPORT": "导出中",
             "DOWNLOAD": "等待下载", "PARSE": "解析中", "PERSIST": "入库中",
             "RETRY": "重试", "DONE": "完成", "PAUSED": "已暂停",
             "ABORTED": "已急停", "FAILED": "失败"}


class MainWindow(QMainWindow):
    def __init__(self, container):
        super().__init__()
        self.c = container
        self.thread = None
        self.elapsed = 0
        self.setWindowTitle("HIS 离线数据采集工具")
        _icon = app_icon()
        if _icon is not None:
            self.setWindowIcon(_icon)
        self.resize(1440, 900)
        self.setMinimumSize(1280, 800)

        # 顶部状态条
        top = QHBoxLayout()
        brand = QLabel()
        _png = resource_path("app.png")
        if _png:
            brand.setPixmap(QPixmap(_png).scaled(
                26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.setFixedSize(30, 30)
        top.addWidget(brand)
        name_lab = QLabel("HIS 数据采集工具")
        name_lab.setStyleSheet("font-weight:bold;color:#1F4E79;font-size:14px;")
        top.addWidget(name_lab)
        top.addSpacing(16)
        top.addWidget(QLabel("作业:"))
        self.job_combo = QComboBox()
        self._fill_jobs()
        top.addWidget(self.job_combo)
        self.state_lab = QLabel("状态：就绪")
        self.state_lab.setStyleSheet("font-weight:bold;color:#1F4E79;")
        top.addWidget(self.state_lab)
        top.addStretch(1)
        self.clock_lab = QLabel()
        top.addWidget(self.clock_lab)
        self.clock = QTimer(self); self.clock.timeout.connect(self._tick_clock)
        self.clock.start(1000); self._tick_clock()

        # 六页
        self.tabs = QTabWidget()
        self.mirror = MirrorView(int(self.c.app.get("mirror", {})
                                     .get("fps", 5)))
        self.logs = LogView()
        monitor = QWidget()
        ml = QVBoxLayout(monitor)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.mirror)
        split.addWidget(self.logs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        ml.addWidget(split)
        self.info_lab = QLabel("当前页面：-　目标：-")
        ml.addWidget(self.info_lab)

        self.tabs.addTab(monitor, "运行监控")
        self.review = ReviewView(container)
        self.tabs.addTab(self.review, "导航图审核")
        self.jobs = JobsView(container, self.run_job_file, self.start_scan)
        self.tabs.addTab(self.jobs, "作业管理")
        self.config_view = ConfigView(container)
        self.tabs.addTab(self.config_view, "配置")
        self.tabs.addTab(DataView(container), "数据查看")
        self.tabs.addTab(AuditView(container), "审计")

        # 底部：进度 + 常驻控制
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setFormat("第 %v 步 / 共 %m 步")
        bottom.addWidget(self.progress, 2)
        self.time_lab = QLabel("已用 00:00")
        bottom.addWidget(self.time_lab)
        self.btn_start = QPushButton("启动")
        self.btn_pause = QPushButton("暂停")
        self.btn_step = QPushButton("单步")
        self.btn_stop = QPushButton("急停")
        self.btn_stop.setStyleSheet("background:#C92A2A;color:white;"
                                    "font-weight:bold;padding:6px 16px;")
        for b, fn in ((self.btn_start, self._start),
                      (self.btn_pause, self._pause),
                      (self.btn_step, self._step),
                      (self.btn_stop, self._emergency)):
            bottom.addWidget(b); b.clicked.connect(fn)
        g = QPushButton("查看导航图")
        g.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        d = QPushButton("打开数据")
        d.clicked.connect(lambda: self.tabs.setCurrentIndex(4))
        bottom.addWidget(g); bottom.addWidget(d)
        self._set_running(False)

        central = QWidget()
        v = QVBoxLayout(central)
        v.addLayout(top)
        v.addWidget(self.tabs, 1)
        v.addLayout(bottom)
        self.setCentralWidget(central)

        # 快捷键：空格暂停 / Esc 急停
        QShortcut(QKeySequence(Qt.Key_Space), self,
                  context=Qt.ApplicationShortcut, activated=self._space)
        QShortcut(QKeySequence(Qt.Key_Escape), self,
                  context=Qt.ApplicationShortcut, activated=self._emergency)

        # 运行计时
        self.run_timer = QTimer(self)
        self.run_timer.timeout.connect(self._tick_run)

        # 告警 → 状态条 + 蜂鸣
        self.c.alerts.sink = self._on_alert
        self.statusBar().showMessage(
            f"就绪　|　凭据库：{self.c.vault_backend()}")

    # ------------------------------------------------------------------ #
    def _fill_jobs(self):
        self.job_combo.clear()
        for p in self.c.center.list_jobs():
            self.job_combo.addItem(p.name)

    def after_target_changed(self):
        """首启向导写入 HIS 目标后，刷新配置页显示。"""
        try:
            self.config_view.load()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
        self.tabs.setCurrentWidget(self.config_view)
        self.statusBar().showMessage("已保存 HIS 目标程序设置，可在“配置”页核对。")

    def _tick_clock(self):
        self.clock_lab.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _tick_run(self):
        self.elapsed += 1
        self.time_lab.setText("已用 " + f"{self.elapsed // 60:02d}:"
                              f"{self.elapsed % 60:02d}")

    def _space(self):
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit,)) or w is not None and \
                w.inherits("QPlainTextEdit"):
            return
        if self.thread is not None:
            self._pause()

    # ---- 控制 ---- #
    def _set_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_step.setEnabled(running)
        self.btn_stop.setEnabled(running)
        if not running:
            self.btn_pause.setText("暂停")

    def _start(self):
        name = self.job_combo.currentText()
        if not name:
            QMessageBox.information(self, "提示", "没有可执行的已签发作业。")
            return
        self.run_job_file(name, self.jobs.sim.isChecked())

    def _pause(self):
        if self.thread is None:
            return
        self.thread.pause()
        paused = self.thread.control.paused
        self.btn_pause.setText("继续" if paused else "暂停")
        self._set_state("PAUSED" if paused else "RUNNING",
                        "已暂停" if paused else "执行中")

    def _step(self):
        if self.thread is not None:
            self.thread.step_once()

    def _emergency(self):
        # 急停：无确认框，立即释放键鼠并停止（gate 50ms 响应）
        if self.thread is None:
            return
        try:
            self.thread.emergency_stop()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
        self._set_state("ABORTED", "已急停")
        self.statusBar().showMessage("急停已触发，正在释放键鼠…")

    def _set_state(self, state, cn):
        color = "#C92A2A" if state in ("FAILED", "ABORTED") else \
                "#1F4E79"
        self.state_lab.setText(f"状态：{cn}")
        self.state_lab.setStyleSheet(f"font-weight:bold;color:{color};")

    # ---- 执行接线 ---- #
    def run_job_file(self, name: str, sim: bool):
        if self.thread is not None:
            QMessageBox.information(self, "提示", "已有作业在执行。")
            return
        try:
            cfg = self.c.center.load_job(name)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "作业加载失败", str(e))
            return
        self._fill_jobs()
        biz = date.today().strftime("%Y%m%d")
        self.thread = RunThread(self.c, cfg, biz, sim=sim)
        self._connect_run(self.thread)
        total = len(cfg.get("job", cfg).get("path", [])) + 4
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(0)
        self.elapsed = 0
        self.tabs.setCurrentIndex(0)
        self.logs.clear()
        self._set_running(True)
        self.thread.start()
        self.run_timer.start(1000)
        self.statusBar().showMessage(
            f"作业 {name} 启动（{'仿真' if sim else '真实'}模式）")

    def _connect_run(self, th: RunThread):
        th.state_changed.connect(self._on_state)
        th.log_appended.connect(self.logs.append)
        th.step_changed.connect(lambda seq, _t: self.progress.setValue(seq))
        th.target_hint.connect(self.mirror.set_hint)
        th.operator_ready.connect(self.mirror.set_operator)
        th.finished_result.connect(self._on_finished)

    def _on_state(self, state, desc):
        cn = _STATE_CN.get(state, state)
        self._set_state(state, cn)
        self.info_lab.setText(f"当前阶段：{cn}　{desc}")
        self.mirror.set_info(f"当前阶段：{cn}")

    def _on_finished(self, result):
        self.run_timer.stop()
        self._set_running(False)
        self.thread = None
        self.mirror.set_operator(None)
        self.jobs.load()
        try:
            self.tabs.widget(4).load()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
        if result is None:
            self._set_state("FAILED", "失败")
            self.statusBar().showMessage("作业异常终止，请查看日志与审计页。")
            return
        if result.success:
            self.progress.setValue(self.progress.maximum())
            self._set_state("DONE", "完成")
            QMessageBox.information(
                self, "执行完成",
                f"成功：{len(result.files)} 个文件，新增 {result.rows_inserted} "
                f"行，更新 {result.rows_updated} 行。")
        else:
            cn = _STATE_CN.get(result.state, result.state)
            self._set_state(result.state, cn)
            QMessageBox.warning(
                self, "作业未成功",
                f"状态：{cn}\n错误码：{result.error_code}\n{result.message}")

    # ---- 扫描接线 ---- #
    def start_scan(self, sim: bool):
        if self.thread is not None:
            QMessageBox.information(self, "提示", "请先结束当前作业。")
            return
        th = ScanThread(self.c, sim=sim)
        th.operator_ready.connect(self.mirror.set_operator)
        th.event.connect(self._on_scan_event)
        th.scan_finished.connect(lambda r: self._on_scan_done(r, th))
        self.thread = th
        self.tabs.setCurrentIndex(0)
        self._set_running(True)
        self.btn_pause.setEnabled(False)
        self.btn_step.setEnabled(False)
        th.start()

    def _on_scan_event(self, kind, kw):
        msg = kw.get("message", kind)
        self.logs.append({"level": "INFO", "message": f"[扫描] {msg}"})

    def _on_scan_done(self, result, th):
        self.mirror.set_operator(None)
        self.thread = None
        self._set_running(False)
        if result.status == "aborted":
            self._set_state("ABORTED", "扫描已中止（图已保存，可断点续扫）")
        else:
            self._set_state("DONE", f"扫描完成：{result.pages}页/"
                                    f"{result.edges}边/危险{result.dangers}")
        self.review.load()
        QMessageBox.information(
            self, "扫描结果",
            f"状态：{result.status}\n页面 {result.pages}，边 {result.edges}，"
            f"危险登记 {result.dangers}。\n可前往“导航图审核”页签发作业。")

    # ---- 告警 ---- #
    def _on_alert(self, alert):
        self.statusBar().showMessage(
            f"[{alert.severity}] {alert.error_code} {alert.message}")
        if alert.severity in ("ERROR", "CRITICAL"):
            QApplication.beep()
