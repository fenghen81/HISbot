"""启动外部 HIS 主程序（C/S 客户端或浏览器均可）。

跨平台封装 subprocess.Popen：
- Windows：CREATE_NEW_PROCESS_GROUP，使其与本工具的 Ctrl-C 信号隔离；
- POSIX：start_new_session，独立进程组，本工具退出不连带杀死 HIS。
仅负责“拉起进程”，不负责窗口绑定（窗口定位见 windowing.resolve_target_window）。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field


def is_windows() -> bool:
    return sys.platform.startswith("win")


def split_args(text: str | Sequence[str] | None) -> list[str]:
    """把 GUI 文本框里的一行启动参数拆成 argv。

    非 Windows 用 POSIX shell 规则（支持引号）；Windows 按空白拆分并去引号。
    """
    if not text:
        return []
    if isinstance(text, (list, tuple)):
        return [str(a) for a in text]
    text = str(text).strip()
    if not text:
        return []
    if is_windows():
        out, buf, q = [], "", None
        for ch in text:
            if q:
                if ch == q:
                    q = None
                else:
                    buf += ch
            elif ch in ('"', "'"):
                q = ch
            elif ch.isspace():
                if buf:
                    out.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            out.append(buf)
        return out
    return shlex.split(text)


@dataclass
class LaunchedProgram:
    process: subprocess.Popen
    path: str
    args: list[str] = field(default_factory=list)

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def terminate(self) -> None:
        """仅在本工具需要时显式调用；正常采集结束不关闭 HIS。"""
        try:
            if self.is_alive():
                self.process.terminate()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)


def resolve_program_path(path: str) -> str:
    """校验并归一化程序路径；找不到可执行文件抛 FileNotFoundError。"""
    if not path or not str(path).strip():
        raise FileNotFoundError("未指定 HIS 主程序路径")
    p = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
    if not os.path.isabs(p):
        p = os.path.abspath(p)
    if not os.path.exists(p):
        raise FileNotFoundError(f"HIS 主程序不存在：{p}")
    if not is_windows() and not os.access(p, os.X_OK):
        raise PermissionError(f"文件不可执行（缺少可执行权限）：{p}")
    return p


def launch_program(path: str, args: str | Sequence[str] | None = None,
                   work_dir: str | None = None) -> LaunchedProgram:
    """启动 HIS 主程序，返回进程句柄。失败抛 OSError/FileNotFoundError。"""
    exe = resolve_program_path(path)
    argv = [exe] + split_args(args)
    cwd = work_dir or os.path.dirname(exe) or None
    popen_kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True, cwd=cwd)
    if is_windows():
        # 新建进程组，避免本工具控制台事件直接传递给 HIS
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        popen_kw["creationflags"] = flags
    else:
        popen_kw["start_new_session"] = True
    proc = subprocess.Popen(argv, **popen_kw)
    return LaunchedProgram(process=proc, path=exe,
                           args=split_args(args))
