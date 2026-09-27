"""程序入口：显示环境校验 → 依赖装配 → 启动主窗口。

用法：python -m hisbot.app.main [--root DIR] [--sim-check]
"""
from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger("hisbot")


def find_root(cli_root: str | None = None) -> str:
    if cli_root:
        return os.path.abspath(cli_root)
    env = os.environ.get("HISBOT_ROOT")
    if env:
        return os.path.abspath(env)
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, "config")):
        return cwd
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.isdir(os.path.join(exe_dir, "config")):
        return exe_dir
    return cwd


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    root = find_root(root)

    from PySide6.QtWidgets import QApplication, QMessageBox

    from ..platform.appselect import is_setup_complete
    from ..ui.branding import app_icon, install_app_id
    from ..ui.main_window import MainWindow
    from .services import Container

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install_app_id()
    qt = QApplication.instance() or QApplication(argv)
    qt.setApplicationName("HISBot")
    icon = app_icon()
    if icon is not None:
        qt.setWindowIcon(icon)
    try:
        qt.setStyle("Fusion")
    except Exception:
        _log.warning("切换 Fusion 风格失败，使用系统默认风格", exc_info=True)
    try:
        from ..ui.theme import MODERN_QSS
        qt.setStyleSheet(MODERN_QSS)
    except Exception:
        _log.warning("加载现代主题失败，界面退回默认样式（检查 theme.py 是否被打包）",
                     exc_info=True)

    container = Container(root)
    problems, allowed = container.check_environment()
    for m in problems:
        container.logger.warn(m, "SCA-000")
    if not allowed:
        text = "\n".join(p.replace("FATAL: ", "") for p in problems)
        QMessageBox.critical(
            None, "显示环境校验未通过",
            "为保证像素级定位准确，必须满足以下条件后方可运行：\n\n"
            f"{text}\n\n请切换 X11、关闭 Wayland、缩放固定 100% 后重试。")
        container.shutdown()
        return 2

    win = MainWindow(container)
    win.show()
    if problems:
        win.statusBar().showMessage("环境告警：" + "；".join(problems))

    from PySide6.QtCore import QTimer

    # 首次启动：引导选择 HIS 应用程序
    if not is_setup_complete(container.site):
        def _run_setup():
            from ..ui.setup_wizard import SetupWizard
            dlg = SetupWizard(container, win)
            if dlg.exec() == SetupWizard.Accepted:
                win.after_target_changed()
            else:
                # 用户选择“稍后手动配置”：记录，不再每次启动强制弹出
                try:
                    node = container.site.setdefault("site", {})
                    node["setup_dismissed"] = True
                    from ..config.settings import dump_yaml
                    dump_yaml(container.site,
                              container.center.resolve("config/site.yaml"))
                    container.reload_config()
                except Exception:
                    _log.warning("写入 setup_dismissed 标记失败", exc_info=True)
        QTimer.singleShot(180, _run_setup)

    # 首启/空配置：自动获取浏览器下载目录；获取不到则弹窗让用户选择；
    # 若无任何作业，按作业流程引导。
    def _guide_workflow():
        from ..config.settings import dump_yaml
        from ..platform.dirs import detect_downloads_dir, is_default_placeholder
        dl = container.app.setdefault("download", {})
        chosen = None
        if is_default_placeholder(dl.get("watch_dir", "")):
            found = detect_downloads_dir()
            if found:
                chosen = found
            else:
                from PySide6.QtWidgets import QFileDialog
                chosen, _ = QFileDialog.getExistingDirectory(
                    win, "未识别到下载目录，请选择浏览器“静默下载”保存位置", "")
            if chosen:
                dl["watch_dir"] = chosen
                try:
                    dump_yaml(container.app,
                              container.center.resolve("config/app.yaml"))
                    container.reload_config()
                    cv = getattr(win, "config_view", None)
                    if cv is not None:
                        cv.load()
                except Exception:
                    _log.warning("保存下载监听目录配置失败", exc_info=True)
        watch = container.center.watch_dir
        try:
            has_jobs = container.repo.count("jobs") > 0
        except Exception:
            has_jobs = True
        if not has_jobs:
            QMessageBox.information(
                win, "欢迎使用 HISBot —— 首次作业引导",
                "按下面三步即可完成第一次自动采集：\n\n"
                "① 核对站点与 HIS 连接：进入「配置」页，确认站点地址、账号，"
                "以及上一步选定的 HIS 程序/窗口绑定。\n"
                "② 新建作业：进入「作业」页，新建作业——选择要采集的 HIS 报表、"
                "字段映射与执行时间。\n"
                "③ 开始运行：进入「采集/监控」页点开始；程序会监听下载目录、"
                "下载完成后自动归档并解析入库。\n\n"
                f"当前下载监听目录：{watch}\n"
                "（如与浏览器实际下载位置不符，可在「配置」页点“自动检测”或“浏览…”修改）。")

    QTimer.singleShot(900, _guide_workflow)

    code = qt.exec()
    container.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
