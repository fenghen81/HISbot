"""品牌资源（应用图标）加载，兼容源码运行与 PyInstaller 冻结后的布局。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import sys
from pathlib import Path


def _candidates(name: str):
    here = Path(__file__).resolve().parent
    pack_root = here.parent
    roots = [
        pack_root / "resources",          # 源码 / 常规安装：hisbot/resources
        Path(getattr(sys, "_MEIPASS", "")) / "hisbot" / "resources",
        Path(getattr(sys, "_MEIPASS", "")) / "resources",
        Path(sys.executable).resolve().parent / "resources",
    ]
    for r in roots:
        p = r / name
        if p.exists():
            return p
    # 兜底：在 _MEIPASS 内浅层查找
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        for p in Path(mp).rglob(name):
            return p
    return None


def resource_path(name: str) -> str | None:
    p = _candidates(name)
    return str(p) if p else None


def app_icon():
    """返回 QIcon；任何异常/缺失都回退为 Qt 默认图标（None）。"""
    try:
        from PySide6.QtGui import QIcon
        ico = resource_path("app.ico")
        png = resource_path("app.png")
        icon = QIcon()
        if ico:
            icon.addFile(ico)          # Windows 任务栏/标题栏优先多帧 ico
        if png:
            icon.addFile(png)
        if not icon.isNull():
            return icon
    except Exception:
        _log.warning("忽略异常 @%s", __name__, exc_info=True)
    return None


def install_app_id() -> None:
    """Windows：设置显式 AppUserModelID，使任务栏显示本应用图标而非 Python。"""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "hospital.hisbot.desktop.1")
    except Exception:
        _log.warning("忽略异常 @%s", __name__, exc_info=True)
