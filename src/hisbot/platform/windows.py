"""Windows 平台实现（文档 4.1 平台对照）。

- 屏幕捕获：mss（GDI/DXGI）
- 窗口管理：EnumWindows / SetForegroundWindow（AttachThreadInput 助攻）
- 键鼠注入：SendInput（绝对鼠标、KEYEVENTF_UNICODE 键盘）
- 缩放：Per-Monitor DPI Awareness + GetDpiForSystem
仅在 win32 下被工厂实例化；本模块在其它平台可安全导入（ctypes 延迟绑定）。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import ctypes
import time
from ctypes import wintypes

from ..core.types import Frame, Rect, WindowInfo
from .base import InputInjector, ScaleProvider, ScreenCapturer

# SendInput 常量
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

_VK = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
       "esc": 0x1B, "escape": 0x1B, "enter": 0x0D, "return": 0x0D,
       "tab": 0x09, "backspace": 0x08, "delete": 0x2E,
       "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
       "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
       "insert": 0x2D, "space": 0x20, "f5": 0x74}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT),
                ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class Win32Capturer(ScreenCapturer):
    def __init__(self):
        self.u32 = ctypes.windll.user32
        self._mss = None
        try:  # Per-Monitor V2 DPI 感知
            self.u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                self.u32.SetProcessDPIAware()
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)

    def screen_size(self) -> tuple[int, int]:
        return (self.u32.GetSystemMetrics(0), self.u32.GetSystemMetrics(1))

    def _window_pid(self, hwnd) -> int:
        try:
            pid = wintypes.DWORD(0)
            self.u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return int(pid.value)
        except Exception:
            return 0

    def _window_info(self, hwnd) -> WindowInfo | None:
        if not hwnd:
            return None
        length = self.u32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            self.u32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        r = wintypes.RECT()
        self.u32.GetWindowRect(hwnd, ctypes.byref(r))
        return WindowInfo(str(int(hwnd) if isinstance(hwnd, int) else hwnd),
                          title, r.left, r.top, r.right - r.left,
                          r.bottom - r.top, self._window_pid(hwnd))

    def list_windows(self) -> list[WindowInfo]:
        out: list[WindowInfo] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _lparam):
            if not self.u32.IsWindowVisible(hwnd):
                return True
            if self.u32.GetWindowTextLengthW(hwnd) <= 0:
                return True
            try:
                info = self._window_info(hwnd)
                if info is not None:
                    out.append(info)
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
            return True

        self.u32.EnumWindows(cb, 0)
        return out

    def get_active_window(self) -> WindowInfo | None:
        """当前前台窗口（GetForegroundWindow）。"""
        try:
            hwnd = self.u32.GetForegroundWindow()
            if not hwnd:
                return None
            return self._window_info(hwnd)
        except Exception:
            return None

    def process_path(self, pid: int) -> str:
        """按 PID 取进程可执行文件完整路径（QueryFullProcessImageNameW）。"""
        if not pid:
            return ""
        try:
            k32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(32768)
                if k32.QueryFullProcessImageNameW(
                        wintypes.HANDLE(h), 0, buf, ctypes.byref(size)):
                    return buf.value or ""
                return ""
            finally:
                k32.CloseHandle(h)
        except Exception:
            return ""

    def focus_window(self, hwid: str) -> bool:
        hwnd = wintypes.HWND(int(hwid))
        try:
            cur = self.u32.GetForegroundWindow()
            cur_tid = self.u32.GetWindowThreadProcessId(cur, None)
            tgt_tid = self.u32.GetWindowThreadProcessId(hwnd, None)
            if cur_tid != tgt_tid:
                self.u32.AttachThreadInput(cur_tid, tgt_tid, True)
            self.u32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ok = bool(self.u32.SetForegroundWindow(hwnd))
            self.u32.BringWindowToTop(hwnd)
            if cur_tid != tgt_tid:
                self.u32.AttachThreadInput(cur_tid, tgt_tid, False)
            return ok
        except Exception:
            return False

    def _grab(self, region: Rect | None):
        import mss
        import numpy as np
        if self._mss is None:
            self._mss = mss.mss()
        if region:
            mon = {"left": region.x, "top": region.y,
                   "width": region.w, "height": region.h}
        else:
            mon = self._mss.monitors[0]
        shot = self._mss.grab(mon)
        return np.array(shot)[:, :, :3].copy()

    def capture(self, region: Rect | None = None) -> Frame:
        return Frame(image=self._grab(region), ts=time.time())

    def capture_window(self, hwid: str) -> tuple[Frame, Rect]:
        hwnd = wintypes.HWND(int(hwid))
        r = wintypes.RECT()
        self.u32.GetWindowRect(hwnd, ctypes.byref(r))
        rect = Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
        return self.capture(rect), rect


class Win32Input(InputInjector):
    def __init__(self):
        self.u32 = ctypes.windll.user32

    def _send(self, inp: _INPUT) -> None:
        self.u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def move_to(self, x: int, y: int, duration_ms: int = 0) -> None:
        W, H = self.u32.GetSystemMetrics(0), self.u32.GetSystemMetrics(1)
        ax = int(x * 65535 / max(W - 1, 1))
        ay = int(y * 65535 / max(H - 1, 1))
        u = _INPUTUNION()
        u.mi = _MOUSEINPUT(ax, ay, 0,
                           MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None)
        self._send(_INPUT(INPUT_MOUSE, u))

    def _mouse(self, flags: int) -> None:
        u = _INPUTUNION()
        u.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
        self._send(_INPUT(INPUT_MOUSE, u))

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.move_to(x, y)
        d, u = (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
        if button == "right":
            d, u = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif button == "middle":
            d, u = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
        self._mouse(d)
        time.sleep(0.06)
        self._mouse(u)

    def double_click(self, x: int, y: int, button: str = "left") -> None:
        self.click(x, y, button)
        time.sleep(0.05)
        self.click(x, y, button)

    def _vk_event(self, vk: int, up: bool) -> None:
        flags = KEYEVENTF_KEYUP if up else 0
        u = _INPUTUNION()
        u.ki = _KEYBDINPUT(vk, 0, flags, 0, None)
        self._send(_INPUT(INPUT_KEYBOARD, u))

    def press(self, key: str) -> None:
        self._vk_event(_VK.get(key.lower(), ord(key[0].upper())), False)

    def release(self, key: str) -> None:
        self._vk_event(_VK.get(key.lower(), ord(key[0].upper())), True)

    def hotkey(self, *keys: str) -> None:
        vks = [_VK.get(k.lower(), ord(k[0].upper())) for k in keys]
        for vk in vks[:-1]:
            self._vk_event(vk, False)
        self._vk_event(vks[-1], False)
        time.sleep(0.03)
        self._vk_event(vks[-1], True)
        for vk in reversed(vks[:-1]):
            self._vk_event(vk, True)

    def type_text(self, text: str, interval_ms: int = 90) -> None:
        # KEYEVENTF_UNICODE 直接送 Unicode，天然支持中文且规避输入法
        for ch in text:
            down = _INPUTUNION()
            down.ki = _KEYBDINPUT(0, ord(ch), KEYEVENTF_UNICODE, 0, None)
            self._send(_INPUT(INPUT_KEYBOARD, down))
            up = _INPUTUNION()
            up.ki = _KEYBDINPUT(0, ord(ch),
                                KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
            self._send(_INPUT(INPUT_KEYBOARD, up))
            if interval_ms:
                time.sleep(min(interval_ms, 200) / 1000.0)

    def scroll(self, dy: int, x: int | None = None,
               y: int | None = None) -> None:
        if x is not None and y is not None:
            self.move_to(x, y)
        for _ in range(min(abs(dy), 20)):
            u = _INPUTUNION()
            u.mi = _MOUSEINPUT(0, 0, 120 if dy > 0 else -120,
                               MOUSEEVENTF_WHEEL, 0, None)
            self._send(_INPUT(INPUT_MOUSE, u))

    def release_all(self) -> None:
        for vk in (0x11, 0x12, 0x10):
            self._vk_event(vk, True)
        for f in (MOUSEEVENTF_LEFTUP, MOUSEEVENTF_RIGHTUP,
                  MOUSEEVENTF_MIDDLEUP):
            self._mouse(f)


class Win32Scale(ScaleProvider):
    def __init__(self):
        self.u32 = ctypes.windll.user32

    def resolution(self) -> tuple[int, int]:
        return (self.u32.GetSystemMetrics(0), self.u32.GetSystemMetrics(1))

    def scale_ratio(self) -> float:
        try:
            return round(self.u32.GetDpiForSystem() / 96.0, 4)
        except Exception:
            return 1.0
