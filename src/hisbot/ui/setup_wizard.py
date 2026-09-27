"""首次启动向导：引导用户选择 HIS 应用程序。

三种方式（任选其一），选中后自动识别并回填 site.yaml 的窗口定位参数：
1. 自动检测当前正在运行的程序（按可执行文件去重，疑似 HIS 置顶）；
2. 3 秒后拾取当前前台窗口（适合先点到 HIS 再操作）；
3. 手动浏览指定 HIS 主程序（.exe）。

识别出的“程序路径 / 窗口标题正则 / 启动参数”在下方可二次调整，确认后
写回 config/site.yaml 并留审计。用户也可“稍后手动配置”跳过。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..platform.appselect import apply_window_choice, build_candidates, derive_title_pattern
from .branding import resource_path

_MODE_CN = {"launch": "启动指定的 HIS 主程序并自动绑定其窗口",
            "active": "拾取当前前台窗口（运行前先把 HIS 点到最前）",
            "title": "按窗口标题正则匹配（HIS 需已登录打开）"}


class SetupWizard(QDialog):
    def __init__(self, container, parent=None):
        super().__init__(parent)
        self.c = container
        self.setWindowTitle("选择 HIS 应用程序 · 首次设置")
        self.setModal(True)
        self.resize(760, 600)
        self._capturer = None
        self._mode = "launch"

        root = QVBoxLayout(self)

        # ---- 头部：图标 + 欢迎语 ---- #
        head = QHBoxLayout()
        logo = QLabel()
        png = resource_path("app.png")
        if png:
            logo.setPixmap(QPixmap(png).scaled(
                56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setFixedSize(64, 64)
        head.addWidget(logo)
        title = QVBoxLayout()
        t = QLabel("选择要采集的 HIS 应用程序")
        tf = t.font(); tf.setPointSize(15); tf.setBold(True)
        t.setFont(tf)
        sub = QLabel("可从正在运行的程序中自动识别，或指定主程序；选择后会自动"
                     "填写程序路径与窗口匹配参数，之后可在“配置”页修改。")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#555;")
        title.addWidget(t); title.addWidget(sub)
        head.addLayout(title, 1)
        root.addLayout(head)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # ---- 页一：正在运行的程序 ---- #
        p1 = QWidget(); l1 = QVBoxLayout(p1)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("当前正在运行、且带窗口的程序："))
        bar.addStretch(1)
        self.btn_refresh = QPushButton("重新检测")
        self.btn_refresh.clicked.connect(self.refresh_running)
        bar.addWidget(self.btn_refresh)
        l1.addLayout(bar)
        self.app_list = QListWidget()
        self.app_list.itemSelectionChanged.connect(self._on_pick_running)
        self.app_list.itemDoubleClicked.connect(lambda *_: self.accept())
        l1.addWidget(self.app_list, 1)
        self.run_hint = QLabel("")
        self.run_hint.setWordWrap(True)
        self.run_hint.setStyleSheet("color:#666;")
        l1.addWidget(self.run_hint)
        self.tabs.addTab(p1, "从运行中的程序选择（推荐）")

        # ---- 页二：拾取前台窗口 ---- #
        p2 = QWidget(); l2 = QVBoxLayout(p2)
        l2.addWidget(QLabel("1）先把 HIS 窗口点到屏幕最前面；\n"
                            "2）点击下面按钮，3 秒后自动读取当前前台窗口；\n"
                            "3）能识别到程序路径时按“启动主程序”绑定，"
                            "否则按“前台窗口”绑定。"))
        row = QHBoxLayout()
        self.btn_pick = QPushButton("3 秒后拾取前台窗口…")
        self.btn_pick.clicked.connect(self._pick_active)
        row.addWidget(self.btn_pick); row.addStretch(1)
        l2.addLayout(row)
        self.pick_result = QLabel("尚未拾取。")
        self.pick_result.setWordWrap(True)
        self.pick_result.setStyleSheet("padding:10px;background:#F2F6FB;")
        l2.addWidget(self.pick_result)
        l2.addStretch(1)
        self.tabs.addTab(p2, "拾取当前前台窗口")

        # ---- 页三：手动指定主程序 ---- #
        p3 = QWidget(); f3 = QFormLayout(p3)
        prow = QHBoxLayout()
        self.manual_path = QLineEdit()
        self.manual_path.setPlaceholderText(r"如 C:\HIS\HisClient.exe")
        b = QPushButton("浏览…")
        b.clicked.connect(self._browse)
        prow.addWidget(self.manual_path); prow.addWidget(b)
        f3.addRow("HIS 主程序", prow)
        self.manual_args = QLineEdit()
        self.manual_args.setPlaceholderText("启动参数，可留空")
        f3.addRow("启动参数", self.manual_args)
        use = QPushButton("使用该程序")
        use.clicked.connect(self._use_manual)
        f3.addRow("", use)
        self.tabs.addTab(p3, "手动指定主程序")

        # ---- 识别参数区 ---- #
        box = QGroupBox("识别到的参数（可调整后确认）")
        form = QFormLayout(box)
        self.f_mode = QLineEdit(); self.f_mode.setReadOnly(True)
        self.f_path = QLineEdit()
        self.f_title = QLineEdit()
        self.f_title.setPlaceholderText("窗口标题正则，可改宽松，如 .*住院.*|.*HIS.*")
        self.f_args = QLineEdit()
        self.f_wait = QSpinBox(); self.f_wait.setRange(1, 120)
        self.f_wait.setSuffix(" 秒"); self.f_wait.setValue(8)
        form.addRow("定位方式", self.f_mode)
        form.addRow("程序路径", self.f_path)
        form.addRow("窗口标题正则", self.f_title)
        form.addRow("启动参数", self.f_args)
        form.addRow("启动后等待", self.f_wait)
        root.addWidget(box)

        # ---- 底部按钮 ---- #
        foot = QHBoxLayout()
        foot.addStretch(1)
        later = QPushButton("稍后手动配置")
        later.clicked.connect(self.reject)
        ok = QPushButton("确认并保存")
        ok.setDefault(True)
        ok.setStyleSheet("background:#1F4E79;color:white;padding:8px 22px;")
        ok.clicked.connect(self._confirm)
        foot.addWidget(later); foot.addWidget(ok)
        root.addLayout(foot)

        QTimer.singleShot(0, self.refresh_running)

    # ------------------------------------------------------------------ #
    def _get_capturer(self):
        if self._capturer is None:
            from ..platform import factory
            self._capturer = factory.create_capturer()
        return self._capturer

    def refresh_running(self):
        self.btn_refresh.setEnabled(False)
        self.app_list.clear()
        self.run_hint.setText("正在检测正在运行的程序…")
        QTimer.singleShot(30, self._scan_running)

    def _scan_running(self):
        try:
            cap = self._get_capturer()
            cands = build_candidates(cap.list_windows(), cap.process_path)
        except Exception as e:  # noqa: BLE001 无显示/平台不支持
            self.run_hint.setText(f"当前环境无法枚举窗口：{e}\n"
                                  "可改用“拾取前台窗口”或“手动指定主程序”。")
            self.btn_refresh.setEnabled(True)
            return
        self._cands = cands
        for c in cands:
            self.app_list.addItem(c.display())
        self.btn_refresh.setEnabled(True)
        if cands:
            n_his = sum(1 for c in cands if c.is_his_like)
            self.run_hint.setText(
                f"检测到 {len(cands)} 个带窗口的程序"
                + (f"，其中 {n_his} 个名称疑似 HIS（已置顶）。" if n_his
                   else "，未发现名称含 HIS/医院 等关键词的程序，请自行辨认。")
                   + "单击选择，双击直接确认。")
            self.app_list.setCurrentRow(0)
        else:
            self.run_hint.setText("未检测到可识别路径的窗口程序。可先启动 HIS，"
                                  "再点“重新检测”，或改用其它页签。")

    def _set_fields(self, mode, path, title, args=""):
        self._mode = mode
        self.f_mode.setText(_MODE_CN.get(mode, mode))
        self.f_path.setText(path or "")
        if title:
            self.f_title.setText(derive_title_pattern(title))
        self.f_args.setText(args or "")
        self.f_wait.setEnabled(mode == "launch")
        self.f_path.setEnabled(mode == "launch")
        self.f_args.setEnabled(mode == "launch")

    def _on_pick_running(self):
        i = self.app_list.currentRow()
        cands = getattr(self, "_cands", [])
        if 0 <= i < len(cands):
            c = cands[i]
            self._set_fields("launch", c.path, c.title)

    # ---- 前台拾取 ---- #
    def _pick_active(self):
        self.btn_pick.setEnabled(False)
        self._countdown(3)

    def _countdown(self, left):
        if left > 0:
            self.btn_pick.setText(f"请把 HIS 点到最前… {left}")
            QTimer.singleShot(1000, lambda: self._countdown(left - 1))
        else:
            self.btn_pick.setText("3 秒后拾取前台窗口…")
            self.btn_pick.setEnabled(True)
            self._do_pick()

    def _do_pick(self):
        try:
            cap = self._get_capturer()
            w = cap.get_active_window()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "拾取失败", str(e))
            return
        if not w:
            self.pick_result.setText("未获取到前台窗口，请重试。")
            return
        path = ""
        try:
            path = (cap.process_path(w.pid) or "").strip()
        except Exception:
            path = ""
        if path:
            self._set_fields("launch", path, w.title)
            self.pick_result.setText(
                f"已拾取：{w.title}\n进程 PID {w.pid}，程序：{path}\n"
                f"将按“启动该主程序”方式绑定。")
        else:
            self._set_fields("active", "", w.title)
            self.pick_result.setText(
                f"已拾取：{w.title}\n进程 PID {w.pid}（未取到程序路径）\n"
                f"将按“前台窗口”方式绑定。")

    # ---- 手动指定 ---- #
    def _browse(self):
        import sys
        filt = ("程序 (*.exe);;所有文件 (*)" if sys.platform.startswith("win")
                else "可执行程序 (*);;所有文件 (*)")
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 HIS 主程序", self.manual_path.text(), filt)
        if path:
            self.manual_path.setText(path)

    def _use_manual(self):
        path = self.manual_path.text().strip()
        if not path:
            QMessageBox.information(self, "提示", "请先选择 HIS 主程序。")
            return
        self._set_fields("launch", path, "", self.manual_args.text())
        QMessageBox.information(
            self, "已选择",
            "已填入程序路径。\n若该程序启动后窗口标题固定，可在下方补一个"
            "“窗口标题正则”（可留空，留空时按启动进程的窗口绑定）。")

    # ---- 确认写回 ---- #
    def _confirm(self):
        mode = self._mode
        path = self.f_path.text().strip()
        title_rx = self.f_title.text().strip()
        if mode == "launch" and not path:
            QMessageBox.warning(self, "缺少程序路径",
                                "“启动主程序”方式需要指定 HIS 主程序。")
            return
        if mode == "title" and not title_rx:
            QMessageBox.warning(self, "缺少标题规则",
                                "请填写窗口标题正则，或改用其它方式。")
            return
        try:
            apply_window_choice(
                self.c.site, mode,
                program_path=path,
                program_args=self.f_args.text(),
                title_pattern=title_rx,
                launch_wait_s=self.f_wait.value())
            from ..config.settings import dump_yaml
            dump_yaml(self.c.site, self.c.center.resolve("config/site.yaml"))
            self.c.reload_config()
            self.c.repo.audit(
                "operator", "his_target_setup", object_type="config",
                detail=f"首次设置向导写入 HIS 目标：mode={mode}, path={path}, "
                       f"title={title_rx}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.accept()
