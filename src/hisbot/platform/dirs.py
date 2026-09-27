"""跨平台“浏览器下载目录”自动探测。

设计目标：
- Windows：优先系统已知文件夹 Downloads（注册表 Shell Folders），其次
  SHGetKnownFolderPath，最后 USERPROFILE\\Downloads；任一存在即用。
- Linux/macOS：~\\Downloads（兼容中文 ~/下载）。
- 全部失败返回 None，由调用方弹目录选择框让用户指定。

探测只判断“目录是否存在”，不做任何写入；纯逻辑可单测。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import os
from pathlib import Path

_DOWNLOADS_KFID = "{374DE290-123F-4565-9164-3C492593E17A}"


def pick_existing(candidates) -> str | None:
    """从候选路径里挑第一个真实存在的目录，返回规范化路径；都没有返回 None。"""
    for c in candidates:
        if not c:
            continue
        try:
            p = os.path.abspath(os.path.expandvars(os.path.expanduser(str(c))))
        except Exception:
            continue
        if os.path.isdir(p):
            return p
    return None


def _windows_candidates() -> list[str]:
    cands: list[str] = []

    # 1) 注册表 Shell Folders（最常见、无需 COM）
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\Shell Folders") as k:
            v, _ = winreg.QueryValueEx(k, _DOWNLOADS_KFID)
            if v:
                cands.append(str(v))
    except Exception:
        _log.warning("忽略异常 @%s", __name__, exc_info=True)

    # 2) SHGetKnownFolderPath（官方 API，最佳努力）
    try:
        import ctypes
        from ctypes import wintypes  # noqa: F401

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong),
                        ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort),
                        ("Data4", ctypes.c_byte * 8)]

        kfid = GUID(0x374DE290, 0x123F, 0x4565,
                    (ctypes.c_byte * 8)(0x91, 0x64, 0x3C, 0x49, 0x25, 0x93,
                                        0xE1, 0x7A))
        ppath = wintypes.LPWSTR()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(kfid), 0, 0, ctypes.byref(ppath))
        if hr == 0 and ppath.value:
            cands.append(ppath.value)
            ctypes.windll.ole32.CoTaskMemFree(ppath)
    except Exception:
        _log.warning("忽略异常 @%s", __name__, exc_info=True)

    # 3) 回退 %USERPROFILE%\Downloads
    up = os.environ.get("USERPROFILE") or os.environ.get("HOMEDRIVE", "") + \
        os.environ.get("HOMEPATH", "")
    if up:
        cands.append(os.path.join(up, "Downloads"))
    return cands


def _posix_candidates() -> list[str]:
    home = str(Path.home())
    return [os.path.join(home, "Downloads"), os.path.join(home, "下载")]


def detect_downloads_dir() -> str | None:
    """返回真实存在的浏览器下载目录；探测不到返回 None。"""
    if os.name == "nt":
        return pick_existing(_windows_candidates())
    return pick_existing(_posix_candidates())


# 与出厂默认值比较：配置里还是占位值时，视为“尚未真正指定”
_PLACEHOLDER_DIRS = {"./data/downloads", "data/downloads", ""}


def is_default_placeholder(path: str | None) -> bool:
    if not path:
        return True
    return os.path.normpath(path).replace("\\", "/").rstrip("/") in \
        {x.rstrip("/") for x in _PLACEHOLDER_DIRS}
