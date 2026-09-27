"""HIS 目标窗口定位（三种方式，统一入口）。

locate_mode：
- "title" ：按窗口标题正则匹配（历史默认方式）
- "active"：直接取当前前台/活动窗口（用户先点到 HIS，再启动/测试）
- "launch"：由本工具启动指定的 HIS 主程序，再按 标题→进程PID→前台窗口 绑定

解析失败时 window=None，由上层退化为全屏 root 捕获并给出告警，绝不静默点错窗口。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from ..core.types import WindowInfo
from .base import ScreenCapturer
from .program import LaunchedProgram, launch_program

VALID_MODES = ("title", "active", "launch")


@dataclass
class ResolveResult:
    window: WindowInfo | None
    method: str                       # 实际命中方式 title/active/pid/none
    message: str
    launched: LaunchedProgram | None = None


def _find_by_pid(capturer: ScreenCapturer, pid: int) -> WindowInfo | None:
    if pid <= 0:
        return None
    for w in capturer.list_windows():
        if w.pid == pid and w.title:
            return w
    return None


def _poll_launched(capturer: ScreenCapturer, prog: LaunchedProgram,
                   title_pattern: str, wait_s: float,
                   sleep: Callable[[float], None]) -> ResolveResult:
    deadline = time.monotonic() + max(0.0, wait_s)
    while True:
        if title_pattern:
            w = capturer.find_window(title_pattern)
            if w is not None:
                return ResolveResult(w, "title",
                                     f"已启动并按标题命中窗口：{w.title}", prog)
        w = _find_by_pid(capturer, prog.pid)
        if w is not None:
            return ResolveResult(w, "pid",
                                 f"已启动并按进程(PID={prog.pid})绑定窗口：{w.title}",
                                 prog)
        w = capturer.get_active_window()
        if w is not None and w.pid == prog.pid:
            return ResolveResult(w, "active",
                                 f"已启动并绑定前台窗口：{w.title}", prog)
        if not prog.is_alive():
            return ResolveResult(
                None, "none",
                f"HIS 主程序启动后已退出（PID={prog.pid}），请检查程序与参数", prog)
        if time.monotonic() >= deadline:
            break
        sleep(0.5)
    return ResolveResult(
        None, "none",
        f"程序已启动（PID={prog.pid}，等待 {wait_s:g}s）但未出现可绑定窗口", prog)


def resolve_target_window(capturer: ScreenCapturer, *,
                          mode: str = "title",
                          title_pattern: str = "",
                          program_path: str = "",
                          program_args=None,
                          work_dir: str = "",
                          launch_wait_s: float = 8.0,
                          sleep: Callable[[float], None] = time.sleep,
                          launcher: Callable | None = None
                          ) -> ResolveResult:
    mode = (mode or "title").strip().lower()
    if mode not in VALID_MODES:
        mode = "title"

    if mode == "active":
        w = capturer.get_active_window()
        if w is not None:
            return ResolveResult(w, "active", f"已拾取前台窗口：{w.title}")
        return ResolveResult(None, "none", "未能获取当前前台窗口（无活动窗口）")

    if mode == "launch":
        do_launch = launcher or launch_program
        prog = do_launch(program_path, program_args, work_dir or None)
        sleep(0.8)  # 给进程创建主窗口留出初始时间
        return _poll_launched(capturer, prog, title_pattern,
                              launch_wait_s, sleep)

    # 默认：标题正则
    if not title_pattern:
        return ResolveResult(None, "none", "未配置窗口标题匹配规则")
    w = capturer.find_window(title_pattern)
    if w is not None:
        return ResolveResult(w, "title", f"已按标题命中窗口：{w.title}")
    return ResolveResult(None, "none",
                         f"没有标题匹配 “{title_pattern}” 的窗口")
