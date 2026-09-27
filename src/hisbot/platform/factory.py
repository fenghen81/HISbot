"""平台工厂：运行时按平台选择适配实现，业务代码零分支（文档 4.1）。"""
from __future__ import annotations

import sys
from pathlib import Path

from .base import CredentialVault, FsWatcher, InputInjector, ScaleProvider, ScreenCapturer
from .fswatch import WatchdogWatcher
from .vault import create_vault


def is_windows() -> bool:
    return sys.platform == "win32"


def platform_name() -> str:
    return "windows" if is_windows() else "linux"


def create_capturer() -> ScreenCapturer:
    if is_windows():
        from .windows import Win32Capturer
        return Win32Capturer()
    from .linux import X11Capturer
    return X11Capturer()


def create_input() -> InputInjector:
    if is_windows():
        from .windows import Win32Input
        return Win32Input()
    from .linux import X11Input
    return X11Input()


def create_scale() -> ScaleProvider:
    if is_windows():
        from .windows import Win32Scale
        return Win32Scale()
    from .linux import X11Scale
    return X11Scale()


def create_watcher() -> FsWatcher:
    return WatchdogWatcher()


def create_credential_vault(config_dir: str | Path) -> CredentialVault:
    return create_vault(config_dir)


def check_display_environment(expected_ratio: float,
                              expected_resolution: tuple[int, int] | None,
                              mismatch_policy: str = "abort"
                              ) -> tuple[list[str], bool]:
    """启动时显示环境校验（文档 4.1 强制约束）。

    返回 (告警信息列表, 是否允许继续)。缩放/分辨率不符且 policy=abort 时
    返回不允许继续（上层抛 SCA-001 / SCA-002）。
    """
    warnings: list[str] = []
    allowed = True
    sp = create_scale()
    ratio = sp.scale_ratio()
    res = sp.resolution()
    if abs(ratio - float(expected_ratio)) > 1e-3:
        msg = (f"显示缩放比为 {ratio:.2f}，与模板记录 {expected_ratio:.2f} "
               f"不一致，可能导致定位偏移（SCA-001）")
        if mismatch_policy == "abort":
            warnings.append("FATAL: " + msg + "；请将缩放固定为 100%")
            allowed = False
        else:
            warnings.append("WARN: " + msg)
    if expected_resolution:
        ew, eh = expected_resolution
        if (ew, eh) != res:
            msg = (f"分辨率为 {res[0]}x{res[1]}，与模板记录 "
                   f"{ew}x{eh} 不一致（SCA-002）")
            if mismatch_policy == "abort":
                warnings.append("FATAL: " + msg)
                allowed = False
            else:
                warnings.append("WARN: " + msg)
    if not is_windows():
        # Wayland 提示
        if _wayland_session():
            warnings.append("FATAL: 检测到 Wayland 会话，屏幕捕获与注入受限，"
                            "请切换至 X11 后重启（AUT-004）")
            allowed = False
    return warnings, allowed


def _wayland_session() -> bool:
    session = (str(__import__("os").environ.get("XDG_SESSION_TYPE", ""))
               .lower())
    wayland_display = __import__("os").environ.get("WAYLAND_DISPLAY")
    disp = __import__("os").environ.get("DISPLAY")
    return session == "wayland" or (bool(wayland_display) and not disp)
