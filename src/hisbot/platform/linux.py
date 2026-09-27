"""Linux（X11）平台实现（文档 4.1 平台对照）。

- 屏幕捕获：优先 Xlib XGetImage（Xvfb / 任意 X11 通用），mss 备选
- 窗口管理：EWMH _NET_CLIENT_LIST / _NET_ACTIVE_WINDOW
- 键鼠注入：XTEST 扩展（XTestFakeMotionEvent / Button / Key）
- 中文输入：CLIPBOARD 选择权 + Ctrl+V 粘贴，规避输入法
- 缩放：Xft.dpi / 96
注意：Wayland 会话下屏幕捕获与注入受限，须切换至 X11（文档前置条件）。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import threading
import time

import numpy as np

from ..core.types import Frame, Rect, WindowInfo
from .base import InputInjector, ScaleProvider, ScreenCapturer

try:
    from Xlib import XK, X, protocol
    from Xlib import display as xdisplay
    from Xlib.ext import xtest
    _HAS_XLIB = True
except Exception:  # pragma: no cover
    _HAS_XLIB = False


# --------------------------------------------------------------------------- #
# X11 剪贴板选择权服务（中文/长文本粘贴）
# --------------------------------------------------------------------------- #
class _ClipboardServer(threading.Thread):
    """短暂持有 CLIPBOARD 选择权并响应目标程序的粘贴请求。"""

    def __init__(self, dpy, text: str, hold: float = 1.2):
        super().__init__(daemon=True)
        self.dpy = dpy
        self.text = text.encode("utf-8")
        self.hold = hold

    def run(self):
        d = self.dpy
        try:
            from Xlib.Xatom import ATOM as XA_ATOM
            from Xlib.Xatom import STRING as XA_STRING
            win = d.screen().root.create_window(0, 0, 1, 1, 0,
                                                 X.InputOnly, X.CopyFromParent)
            clipboard = d.intern_atom("CLIPBOARD")
            targets = d.intern_atom("TARGETS")
            utf8 = d.intern_atom("UTF8_STRING")
            d.set_selection_owner(win, clipboard, X.CurrentTime)
            d.sync()
            deadline = time.time() + self.hold
            while time.time() < deadline:
                if d.pending_events():
                    ev = d.next_event()
                    if ev.type == X.SelectionRequest:
                        prop = ev.property or ev.target
                        if ev.target == targets:
                            win.change_property(prop, XA_ATOM, 32,
                                               [targets, utf8, XA_STRING])
                        else:
                            win.change_property(prop, ev.target, 8, self.text)
                        resp = protocol.event.SelectionNotify(
                            time=X.CurrentTime, requestor=ev.requestor,
                            selection=ev.selection, target=ev.target,
                            property=prop)
                        ev.requestor.send_event(resp)
                        d.sync()
                        if ev.target != targets:
                            return
                else:
                    d.flush()
                    time.sleep(0.02)
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)


# --------------------------------------------------------------------------- #
# 屏幕捕获 / 窗口管理
# --------------------------------------------------------------------------- #
class X11Capturer(ScreenCapturer):
    def __init__(self):
        if not _HAS_XLIB:
            raise RuntimeError("python-xlib 不可用，无法在 Linux 下驱动 X11")
        self.d = xdisplay.Display()
        self._mss = None

    def screen_size(self) -> tuple[int, int]:
        s = self.d.screen()
        return s.width_in_pixels, s.height_in_pixels

    # 窗口枚举 ------------------------------------------------------------- #
    def _window_pid(self, w) -> int:
        try:
            atom = self.d.intern_atom("_NET_WM_PID")
            prop = w.get_full_property(atom, X.AnyPropertyType)
            if prop and prop.value:
                return int(prop.value[0])
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
        return 0

    def _window_info(self, w, root) -> WindowInfo | None:
        try:
            attr = w.get_attributes()
            if attr.map_state != X.IsViewable:
                return None
            name_atom = self.d.intern_atom("_NET_WM_NAME")
            name = ""
            np_ = w.get_full_property(name_atom, X.AnyPropertyType)
            if np_ and np_.value:
                name = bytes(np_.value).decode("utf-8", "ignore")
            if not name:
                name = w.get_wm_name() or ""
            g = w.get_geometry()
            t = w.translate_coords(root, 0, 0)
            return WindowInfo(str(int(w.id)),
                              name, t.x, t.y, g.width, g.height,
                              self._window_pid(w))
        except Exception:
            return None

    def list_windows(self) -> list[WindowInfo]:
        root = self.d.screen().root
        atom = self.d.intern_atom("_NET_CLIENT_LIST")
        prop = root.get_full_property(atom, X.AnyPropertyType)
        out: list[WindowInfo] = []
        if not prop:
            return out
        for wid in prop.value:
            try:
                w = self.d.create_resource_object("window", int(wid))
                info = self._window_info(w, root)
                if info is not None:
                    out.append(info)
            except Exception:
                continue
        return out

    def get_active_window(self) -> WindowInfo | None:
        """通过 EWMH _NET_ACTIVE_WINDOW 读取当前前台窗口。"""
        try:
            root = self.d.screen().root
            atom = self.d.intern_atom("_NET_ACTIVE_WINDOW")
            prop = root.get_full_property(atom, X.AnyPropertyType)
            if not prop or not prop.value or int(prop.value[0]) == 0:
                return None
            w = self.d.create_resource_object("window", int(prop.value[0]))
            return self._window_info(w, root)
        except Exception:
            return None

    def process_path(self, pid: int) -> str:
        """Linux 下通过 /proc/<pid>/exe 符号链接取可执行文件路径。"""
        if not pid or pid <= 0:
            return ""
        import os
        try:
            return os.path.realpath(f"/proc/{int(pid)}/exe")
        except Exception:
            return ""

    def focus_window(self, hwid: str) -> bool:
        try:
            win = self.d.create_resource_object("window", int(hwid))
            root = self.d.screen().root
            active = self.d.intern_atom("_NET_ACTIVE_WINDOW")
            win.map()
            self.d.set_input_focus(win, X.RevertToPointerRoot, X.CurrentTime)
            ev = protocol.event.ClientMessage(
                window=win, client_type=active,
                data=(32, [2, X.CurrentTime, 0, 0, 0]))
            root.send_event(ev, event_mask=(X.SubstructureRedirectMask |
                                            X.SubstructureNotifyMask))
            try:
                win.raise_window()
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
            self.d.sync()
            self.d.set_input_focus(win, X.RevertToPointerRoot, X.CurrentTime)
            self.d.sync()
            return True
        except Exception:
            return False

    # 截图 ----------------------------------------------------------------- #
    def _grab_xlib(self, region: Rect | None) -> np.ndarray:
        W, H = self.screen_size()
        r = region.clamp(W, H) if region else Rect(0, 0, W, H)
        raw = self.d.screen().root.get_image(
            r.x, r.y, r.w, r.h, X.ZPixmap, 0xFFFFFFFF)
        from PIL import Image
        img = Image.frombytes("RGB", (r.w, r.h), raw.data, "raw", "BGRX")
        return np.array(img)[:, :, ::-1].copy()  # RGB->BGR

    def _grab_mss(self, region: Rect | None) -> np.ndarray | None:
        try:
            import mss
            if self._mss is None:
                self._mss = mss.MSS()
            mon = self._mss.monitors[0]
            shot = self._mss.grab(mon if not region else {
                "left": region.x, "top": region.y,
                "width": region.w, "height": region.h})
            arr = np.array(shot)  # BGRA
            return arr[:, :, :3].copy()
        except Exception:
            return None

    def capture(self, region: Rect | None = None) -> Frame:
        img = self._grab_xlib(region)
        if img is None or img.size == 0:
            img = self._grab_mss(region)
        if img is None:
            from ..core.errors import CaptureError
            raise CaptureError("X11 屏幕捕获失败（检查会话是否为 X11）")
        return Frame(image=img, ts=time.time())

    def capture_window(self, hwid: str) -> tuple[Frame, Rect]:
        win = self.d.create_resource_object("window", int(hwid))
        g = win.get_geometry()
        t = win.translate_coords(self.d.screen().root, 0, 0)
        r = Rect(t.x, t.y, g.width, g.height)
        return self.capture(r), r


# --------------------------------------------------------------------------- #
# 键鼠注入
# --------------------------------------------------------------------------- #
_NEED_SHIFT = set('~!@#$%^&*()_+{}|:"<>?ABCDEFGHIJKLMNOPQRSTUVWXYZ')

_SPECIAL = {
    "ctrl": XK.XK_Control_L, "control": XK.XK_Control_L,
    "alt": XK.XK_Alt_L, "shift": XK.XK_Shift_L, "super": XK.XK_Super_L,
    "esc": XK.XK_Escape, "escape": XK.XK_Escape,
    "enter": XK.XK_Return, "return": XK.XK_Return,
    "tab": XK.XK_Tab, "backspace": XK.XK_BackSpace, "delete": XK.XK_Delete,
    "up": XK.XK_Up, "down": XK.XK_Down, "left": XK.XK_Left,
    "right": XK.XK_Right, "home": XK.XK_Home, "end": XK.XK_End,
    "pageup": XK.XK_Page_Up, "pagedown": XK.XK_Page_Down,
    "insert": XK.XK_Insert, "space": XK.XK_space, "f5": XK.XK_F5,
}

_BUTTON = {"left": 1, "middle": 2, "right": 3}
_MOD_KEYCODES: list[int] = []


class X11Input(InputInjector):
    def __init__(self):
        if not _HAS_XLIB:
            raise RuntimeError("python-xlib 不可用")
        self.d = xdisplay.Display()

    def move_to(self, x: int, y: int, duration_ms: int = 0) -> None:
        xtest.fake_input(self.d, X.MotionNotify, x=x, y=y)
        self.d.sync()

    def _button(self, button: str, down: bool) -> None:
        xtest.fake_input(self.d, X.ButtonPress if down else X.ButtonRelease,
                         _BUTTON.get(button, 1))
        self.d.sync()

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.move_to(x, y)
        self._button(button, True)
        self._button(button, False)

    def double_click(self, x: int, y: int, button: str = "left") -> None:
        self.click(x, y, button)
        time.sleep(0.05)
        self.click(x, y, button)

    def _key(self, keysym: int, down: bool) -> None:
        code = self.d.keysym_to_keycode(keysym)
        if code == 0:
            return
        xtest.fake_input(self.d, X.KeyPress if down else X.KeyRelease, code)
        self.d.sync()

    def press(self, key: str) -> None:
        k = key.lower()
        self._key(_SPECIAL.get(k, ord(k[0]) if k else 0), True)

    def release(self, key: str) -> None:
        k = key.lower()
        self._key(_SPECIAL.get(k, ord(k[0]) if k else 0), False)

    def hotkey(self, *keys: str) -> None:
        codes = []
        for k in keys:
            kl = k.lower()
            codes.append(_SPECIAL.get(kl, ord(k[0]) if k else 0))
        for ks in codes[:-1]:           # 修饰键按下
            self._key(ks, True)
        self._key(codes[-1], True)      # 主键
        time.sleep(0.03)
        self._key(codes[-1], False)
        for ks in reversed(codes[:-1]):
            self._key(ks, False)

    def scroll(self, dy: int, x: int | None = None,
               y: int | None = None) -> None:
        if x is not None and y is not None:
            self.move_to(x, y)
        btn = 4 if dy > 0 else 5
        for _ in range(min(abs(dy), 20)):
            self._button_id(btn, True)
            self._button_id(btn, False)

    def _button_id(self, bid: int, down: bool) -> None:
        xtest.fake_input(self.d, X.ButtonPress if down else X.ButtonRelease,
                         bid)
        self.d.sync()

    def type_text(self, text: str, interval_ms: int = 90) -> None:
        if not text:
            return
        # 非 ASCII（中文等）走剪贴板粘贴
        if any(ord(c) > 127 for c in text):
            self._paste_unicode(text)
            return
        for ch in text:
            need_shift = ch in _NEED_SHIFT
            if need_shift:
                self._key(XK.XK_Shift_L, True)
            self._key(ord(ch), True)
            time.sleep(0.02)
            self._key(ord(ch), False)
            if need_shift:
                self._key(XK.XK_Shift_L, False)
            if interval_ms:
                time.sleep(min(interval_ms, 200) / 1000.0)

    def _paste_unicode(self, text: str) -> None:
        srv = _ClipboardServer(xdisplay.Display(), text)
        srv.start()
        time.sleep(0.15)
        self.hotkey("ctrl", "v")
        srv.join(timeout=1.5)

    def release_all(self) -> None:
        """急停：抬起全部修饰键与鼠标三键。"""
        for ks in (XK.XK_Control_L, XK.XK_Alt_L, XK.XK_Shift_L,
                   XK.XK_Super_L):
            try:
                self._key(ks, False)
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
        for bid in (1, 2, 3):
            try:
                self._button_id(bid, False)
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)


# --------------------------------------------------------------------------- #
# 缩放
# --------------------------------------------------------------------------- #
class X11Scale(ScaleProvider):
    def __init__(self):
        self.d = xdisplay.Display()
        s = self.d.screen()
        self._res = (s.width_in_pixels, s.height_in_pixels)

    def resolution(self) -> tuple[int, int]:
        return self._res

    def scale_ratio(self) -> float:
        try:
            dpi = self.d.get_default_resource("", "Xft.dpi")
            if dpi:
                return round(float(dpi) / 96.0, 4)
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
        return 1.0


def x11_available() -> bool:
    return _HAS_XLIB
