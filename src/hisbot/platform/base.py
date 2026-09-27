"""平台适配层抽象接口（文档 4.1）。

上层只依赖本模块抽象基类，运行时由工厂按平台选择实现，业务代码零分支。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from ..core.types import Frame, FsEvent, Handle, Rect, WindowInfo


class ScreenCapturer(ABC):
    """屏幕/窗口捕获 + 窗口管理。"""

    @abstractmethod
    def list_windows(self) -> list[WindowInfo]: ...

    @abstractmethod
    def focus_window(self, hwid: str) -> bool: ...

    @abstractmethod
    def capture(self, region: Rect | None = None) -> Frame: ...

    @abstractmethod
    def capture_window(self, hwid: str) -> tuple[Frame, Rect]:
        """截取指定窗口客户区，返回帧与该窗口在屏幕上的外接矩形。"""

    @abstractmethod
    def screen_size(self) -> tuple[int, int]: ...

    def find_window(self, title_pattern: str) -> WindowInfo | None:
        import re
        rx = re.compile(title_pattern)
        for w in self.list_windows():
            if w.title and (rx.search(w.title) or w.title == title_pattern):
                return w
        return None

    def get_active_window(self) -> WindowInfo | None:
        """当前前台/活动窗口；不支持或无前台窗口时返回 None。"""
        return None

    def process_path(self, pid: int) -> str:
        """窗口所属进程的可执行文件绝对路径；取不到返回空串。

        用于“从正在运行的程序中选择 HIS”，选中后可直接回填启动路径。
        默认不支持；由各平台实现覆盖。
        """
        return ""


class InputInjector(ABC):
    """系统级键鼠注入（无需目标程序配合）。"""

    @abstractmethod
    def move_to(self, x: int, y: int, duration_ms: int = 300) -> None: ...

    @abstractmethod
    def click(self, x: int, y: int, button: str = "left") -> None: ...

    @abstractmethod
    def double_click(self, x: int, y: int, button: str = "left") -> None: ...

    @abstractmethod
    def press(self, key: str) -> None: ...

    @abstractmethod
    def release(self, key: str) -> None: ...

    @abstractmethod
    def type_text(self, text: str, interval_ms: int = 90) -> None: ...

    @abstractmethod
    def hotkey(self, *keys: str) -> None: ...

    @abstractmethod
    def scroll(self, dy: int, x: int | None = None,
               y: int | None = None) -> None: ...

    @abstractmethod
    def release_all(self) -> None:
        """急停调用：立即抬起所有按键/鼠标键，释放控制权。"""


class FsWatcher(ABC):
    """下载目录文件系统事件监听（事件驱动 + 轮询兜底由上层组合）。"""

    @abstractmethod
    def watch(self, path: str,
              cb: Callable[[FsEvent], None]) -> Handle: ...

    @abstractmethod
    def stop(self, handle: Handle) -> None: ...


class CredentialVault(ABC):
    """凭据保护：系统凭据链（Windows DPAPI / Linux Secret Service）。"""

    @abstractmethod
    def save(self, key: str, secret: str) -> None: ...

    @abstractmethod
    def load(self, key: str) -> str | None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def backend(self) -> str: ...


class ScaleProvider(ABC):
    """显示缩放检测（强制固定 100%，文档 4.1 约束）。"""

    @abstractmethod
    def scale_ratio(self) -> float: ...

    @abstractmethod
    def resolution(self) -> tuple[int, int]: ...
