"""配置页、作业管理页、数据查看页、审计页（文档 6.3 / F-01/F-17/F-18）。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")


from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config.settings import dump_yaml


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
class ConfigView(QWidget):
    def __init__(self, container, parent=None):
        super().__init__(parent)
        self.c = container
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.site_id = QLineEdit()
        self.site_name = QLineEdit()
        self.base_url = QLineEdit()
        self.browser = QComboBox()
        self.browser.addItems(["chrome", "edge", "firefox"])
        self.watch = QLineEdit()
        self.archive = QLineEdit()
        self.quarantine = QLineEdit()
        self.fps = QSpinBox(); self.fps.setRange(1, 10)
        self.dl_timeout = QSpinBox(); self.dl_timeout.setRange(5000, 3600000)
        self.dl_timeout.setSingleStep(10000)
        self.page_timeout = QSpinBox(); self.page_timeout.setRange(
            1000, 600000); self.page_timeout.setSingleStep(1000)
        form.addRow("站点ID", self.site_id)
        form.addRow("站点名称", self.site_name)
        form.addRow("站点地址", self.base_url)
        form.addRow("浏览器", self.browser)

        # ---- HIS 窗口定位 ----
        self.locate_mode = QComboBox()
        self.locate_mode.addItem("按窗口标题匹配", "title")
        self.locate_mode.addItem("拾取当前前台窗口", "active")
        self.locate_mode.addItem("启动指定的 HIS 主程序", "launch")
        self.win_pattern = QLineEdit()
        prog_row = QHBoxLayout()
        self.program_path = QLineEdit()
        self.program_path.setPlaceholderText(
            r"如 C:\HIS\HisClient.exe 或 /usr/bin/his-client")
        prog_browse = QPushButton("浏览…")
        prog_browse.clicked.connect(self._browse_program)
        prog_row.addWidget(self.program_path)
        prog_row.addWidget(prog_browse)
        self.program_args = QLineEdit()
        self.program_args.setPlaceholderText("启动参数，可留空，如 --env prod")
        self.launch_wait = QSpinBox()
        self.launch_wait.setRange(1, 120)
        self.launch_wait.setSuffix(" 秒")
        form.addRow("窗口定位方式", self.locate_mode)
        form.addRow("窗口标题正则", self.win_pattern)
        form.addRow("HIS 主程序", prog_row)
        form.addRow("启动参数", self.program_args)
        form.addRow("启动后等待", self.launch_wait)
        win_btns = QHBoxLayout()
        self.btn_wizard = QPushButton("选择 HIS 程序向导…")
        self.btn_wizard.setStyleSheet(
            "background:#2E86DE;color:white;padding:6px 14px;font-weight:bold;")
        self.btn_wizard.clicked.connect(self._open_wizard)
        self.btn_test_win = QPushButton("测试窗口定位")
        self.btn_pick_win = QPushButton("3 秒后拾取前台窗口…")
        self.btn_test_win.clicked.connect(self._test_locate)
        self.btn_pick_win.clicked.connect(self._pick_active)
        win_btns.addWidget(self.btn_wizard)
        win_btns.addWidget(self.btn_test_win)
        win_btns.addWidget(self.btn_pick_win)
        win_btns.addStretch(1)
        form.addRow("", win_btns)
        self.locate_mode.currentIndexChanged.connect(self._on_mode)

        watch_row = QHBoxLayout()
        watch_row.addWidget(self.watch)
        btn_detect = QPushButton("自动检测")
        btn_detect.setToolTip("自动识别当前 Windows 账户的浏览器默认下载目录")
        btn_detect.clicked.connect(self._detect_watch_dir)
        watch_row.addWidget(btn_detect)
        btn_watch_browse = QPushButton("浏览…")
        btn_watch_browse.clicked.connect(lambda: self._browse_dir(self.watch))
        watch_row.addWidget(btn_watch_browse)
        form.addRow("下载监听目录", watch_row)
        form.addRow("归档目录", self.archive)
        form.addRow("隔离目录", self.quarantine)
        form.addRow("镜像帧率", self.fps)
        form.addRow("下载超时(ms)", self.dl_timeout)
        form.addRow("页面超时(ms)", self.page_timeout)
        lay.addLayout(form)

        lay.addWidget(QLabel("导出关键词（每行一个）"))
        self.k_export = QPlainTextEdit(); self.k_export.setFixedHeight(70)
        lay.addWidget(self.k_export)
        lay.addWidget(QLabel("危险黑名单词（每行一个）"))
        self.k_black = QPlainTextEdit(); self.k_black.setFixedHeight(90)
        lay.addWidget(self.k_black)
        lay.addWidget(QLabel("安全导航词（每行一个）"))
        self.k_nav = QPlainTextEdit(); self.k_nav.setFixedHeight(70)
        lay.addWidget(self.k_nav)

        cred = QHBoxLayout()
        cred.addWidget(QLabel("HIS账号"))
        self.account = QLineEdit()
        cred.addWidget(self.account)
        cred.addWidget(QLabel("口令"))
        self.password = QLineEdit(); self.password.setEchoMode(
            QLineEdit.Password)
        cred.addWidget(self.password)
        save_cred = QPushButton("保存凭据")
        save_cred.clicked.connect(self._save_cred)
        cred.addWidget(save_cred)
        self.vault_lab = QLabel()
        cred.addWidget(self.vault_lab)
        lay.addLayout(cred)

        save = QPushButton("保存配置（热加载，修改留审计）")
        save.setStyleSheet("background:#1F4E79;color:white;padding:8px;")
        save.clicked.connect(self._save)
        lay.addWidget(save)
        lay.addStretch(1)
        self.load()

    def load(self):
        c, a, k = self.c, self.c.app, self.c.kw
        s = c.site.get("site", {})
        self.site_id.setText(s.get("site_id", ""))
        self.site_name.setText(s.get("name", ""))
        self.base_url.setText(s.get("base_url", ""))
        self.browser.setCurrentText(s.get("browser", "chrome"))
        self.win_pattern.setText(s.get("window_title_pattern", ""))
        mode = s.get("locate_mode", "title")
        mi = self.locate_mode.findData(mode)
        self.locate_mode.setCurrentIndex(mi if mi >= 0 else 0)
        self.program_path.setText(s.get("program_path", ""))
        self.program_args.setText(s.get("program_args", ""))
        self.launch_wait.setValue(int(s.get("launch_wait_s", 8) or 8))
        self._on_mode()
        d = a.get("download", {})
        self.watch.setText(d.get("watch_dir", ""))
        self.archive.setText(d.get("archive_dir", ""))
        self.quarantine.setText(d.get("quarantine_dir", ""))
        self.fps.setValue(int(a.get("mirror", {}).get("fps", 5)))
        self.dl_timeout.setValue(int(a.get("timing", {})
                                     .get("download_timeout_ms", 120000)))
        self.page_timeout.setValue(int(a.get("timing", {})
                                       .get("page_load_timeout_ms", 10000)))
        self.k_export.setPlainText(
            "\n".join(k.get("export_keywords", [])))
        self.k_black.setPlainText(
            "\n".join(k.get("blacklist_keywords", [])))
        self.k_nav.setPlainText(
            "\n".join(k.get("nav_safe_keywords", [])))
        acct, _ = c.get_credential()
        self.account.setText(acct)
        self.vault_lab.setText(f"凭据库：{c.vault_backend()}")

    def _lines(self, w):
        return [x.strip() for x in w.toPlainText().splitlines() if x.strip()]

    def _save(self):
        c = self.c
        c.site["site"]["site_id"] = self.site_id.text().strip()
        c.site["site"]["name"] = self.site_name.text().strip()
        c.site["site"]["base_url"] = self.base_url.text().strip()
        c.site["site"]["browser"] = self.browser.currentText()
        c.site["site"]["locate_mode"] = self.locate_mode.currentData()
        c.site["site"]["window_title_pattern"] = self.win_pattern.text().strip()
        c.site["site"]["program_path"] = self.program_path.text().strip()
        c.site["site"]["program_args"] = self.program_args.text().strip()
        c.site["site"]["launch_wait_s"] = self.launch_wait.value()
        c.app["download"]["watch_dir"] = self.watch.text().strip()
        c.app["download"]["archive_dir"] = self.archive.text().strip()
        c.app["download"]["quarantine_dir"] = self.quarantine.text().strip()
        c.app["mirror"]["fps"] = self.fps.value()
        c.app["timing"]["download_timeout_ms"] = self.dl_timeout.value()
        c.app["timing"]["page_load_timeout_ms"] = self.page_timeout.value()
        c.kw["export_keywords"] = self._lines(self.k_export)
        c.kw["blacklist_keywords"] = self._lines(self.k_black)
        c.kw["nav_safe_keywords"] = self._lines(self.k_nav)
        dump_yaml(c.app, c.center.resolve("config/app.yaml"))
        dump_yaml(c.site, c.center.resolve("config/site.yaml"))
        dump_yaml(c.kw, c.center.resolve("config/keywords.yaml"))
        c.reload_config()
        c.repo.audit("operator", "config_update", object_type="config",
                     detail="站点/目录/超时/关键词已修改并热加载")
        QMessageBox.information(self, "已保存", "配置已保存并热加载。")

    # ---- HIS 窗口定位 ----
    def _on_mode(self):
        mode = self.locate_mode.currentData()
        is_launch = mode == "launch"
        self.program_path.setEnabled(is_launch)
        self.program_args.setEnabled(is_launch)
        self.launch_wait.setEnabled(is_launch)
        self.win_pattern.setEnabled(mode in ("title", "launch"))

    def _browse_program(self):
        import sys
        filt = ("程序 (*.exe);;所有文件 (*)" if sys.platform.startswith("win")
                else "可执行程序 (*);;所有文件 (*)")
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 HIS 主程序", self.program_path.text(), filt)
        if path:
            self.program_path.setText(path)

    def _browse_dir(self, line_edit):
        """让用户选一个目录，并填入指定输入框。"""
        start = line_edit.text().strip() or ""
        d = QFileDialog.getExistingDirectory(
            self, "选择文件夹（浏览器静默下载到这里）", start)
        if d:
            line_edit.setText(d)

    def _detect_watch_dir(self):
        """自动识别浏览器下载目录；失败则弹目录选择框让用户指定。"""
        from ..platform.dirs import detect_downloads_dir
        found = detect_downloads_dir()
        if found:
            self.watch.setText(found)
            QMessageBox.information(
                self, "已自动识别",
                "识别到浏览器默认下载目录：\n" + found +
                "\n\n如与实际不符，可点“浏览…”手动更正后保存。")
            return
        # 自动获取不到 → 弹窗让用户选择
        QMessageBox.warning(
            self, "未自动识别到下载目录",
            "无法自动定位浏览器下载目录，请手动选择浏览器“静默下载”保存到的文件夹"
            "（通常是 此电脑\\下载 或浏览器设置里指定的下载位置）。")
        self._browse_dir(self.watch)


    def _make_capturer(self):
        from ..platform import factory
        return factory.create_capturer()

    def _test_locate(self):
        try:
            cap = self._make_capturer()
        except Exception as e:  # 无显示环境/平台不支持
            QMessageBox.warning(self, "平台不可用", f"无法访问桌面窗口：{e}")
            return
        from ..platform.windowing import resolve_target_window
        try:
            r = resolve_target_window(
                cap, mode=self.locate_mode.currentData(),
                title_pattern=self.win_pattern.text().strip(),
                program_path=self.program_path.text().strip(),
                program_args=self.program_args.text().strip(),
                launch_wait_s=float(self.launch_wait.value()))
        except FileNotFoundError as e:
            QMessageBox.warning(self, "程序路径无效", str(e))
            return
        except PermissionError as e:
            QMessageBox.warning(self, "程序不可执行", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "定位失败", str(e))
            return
        if r.window is not None:
            w = r.window
            QMessageBox.information(
                self, "定位成功",
                f"{r.message}\n\n句柄：{w.hwid}\n标题：{w.title}\n"
                f"进程PID：{w.pid}\n区域：({w.x},{w.y}) {w.w}×{w.h}\n\n"
                f"请点击“保存配置”后再运行作业。")
        else:
            QMessageBox.warning(self, "未定位到窗口", r.message)

    def _pick_active(self):
        QMessageBox.information(
            self, "拾取前台窗口",
            "点击“确定”后有 3 秒时间，请用鼠标点击目标 HIS 窗口，"
            "使它成为屏幕最前面的窗口，3 秒后自动读取。")
        self.btn_pick_win.setEnabled(False)
        self.btn_pick_win.setText("请切换到 HIS 窗口… 3")

        def grab():
            self.btn_pick_win.setEnabled(True)
            self.btn_pick_win.setText("3 秒后拾取前台窗口…")
            try:
                w = self._make_capturer().get_active_window()
            except Exception as e:
                QMessageBox.warning(self, "拾取失败", str(e))
                return
            if not w:
                QMessageBox.warning(self, "拾取失败", "未获取到前台窗口。")
                return
            idx = self.locate_mode.findData("active")
            self.locate_mode.setCurrentIndex(idx)
            QMessageBox.information(
                self, "拾取成功",
                f"已绑定当前前台窗口：\n标题：{w.title}\n进程PID：{w.pid}\n"
                f"区域：({w.x},{w.y}) {w.w}×{w.h}\n\n"
                f"运行时会自动聚焦该窗口。请点击“保存配置”生效。")

        def tick(left):
            if left > 1:
                self.btn_pick_win.setText(f"请切换到 HIS 窗口… {left - 1}")
                QTimer.singleShot(1000, lambda: tick(left - 1))
            else:
                QTimer.singleShot(200, grab)

        QTimer.singleShot(1000, lambda: tick(3))

    def _open_wizard(self):
        """重新打开“选择 HIS 程序”向导，确认后刷新本页。"""
        from .setup_wizard import SetupWizard
        dlg = SetupWizard(self.c, self)
        if dlg.exec() == SetupWizard.Accepted:
            self.load()

    def _save_cred(self):
        if not self.account.text().strip():
            QMessageBox.warning(self, "缺少账号", "请填写 HIS 账号。")
            return
        self.c.set_credential(self.account.text().strip(),
                              self.password.text())
        self.c.repo.audit("operator", "credential_update",
                          object_type="credential",
                          detail="更新 HIS 账号凭据（口令不记录明文）")
        QMessageBox.information(self, "已保存",
                                f"凭据已加密保存（{self.c.vault_backend()}）。")


# ====================================================================== #
# 作业管理页
# ====================================================================== #
