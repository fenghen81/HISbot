"""HIS 窗口定位与主程序启动测试。"""
import os
import stat
import sys
import time

import pytest

from hisbot.core.types import Frame, Rect, WindowInfo
from hisbot.platform.base import ScreenCapturer
from hisbot.platform.program import launch_program, resolve_program_path, split_args
from hisbot.platform.windowing import resolve_target_window


class FakeCapturer(ScreenCapturer):
    def __init__(self, windows=None, active=None):
        self._windows = windows or []
        self._active = active

    def list_windows(self):
        return list(self._windows)

    def get_active_window(self):
        return self._active

    def focus_window(self, hwid):
        return True

    def capture(self, region=None):
        return Frame(image=None, ts=time.time())

    def capture_window(self, hwid):
        return self.capture(), Rect(0, 0, 100, 100)

    def screen_size(self):
        return (100, 100)


# ---------------- 参数拆分 ---------------- #
def test_split_args_posix():
    assert split_args("--env prod --name '住院 HIS'") == [
        "--env", "prod", "--name", "住院 HIS"]
    assert split_args("") == []
    assert split_args(None) == []
    assert split_args(["a", "b"]) == ["a", "b"]


def test_split_args_windows(monkeypatch):
    monkeypatch.setattr("hisbot.platform.program.is_windows", lambda: True)
    assert split_args('--env prod --name "住院 HIS"') == [
        "--env", "prod", "--name", "住院 HIS"]


# ---------------- 程序路径与启动 ---------------- #
def test_resolve_program_path_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_program_path(str(tmp_path / "nope.exe"))
    with pytest.raises(FileNotFoundError):
        resolve_program_path("")


def test_resolve_program_path_not_executable(tmp_path):
    f = tmp_path / "his.sh"
    f.write_text("echo hi")
    f.chmod(0o644)
    if not sys.platform.startswith("win"):
        with pytest.raises(PermissionError):
            resolve_program_path(str(f))


def test_launch_and_terminate_program():
    prog = launch_program("/bin/sleep", "30")
    try:
        assert prog.pid > 0
        assert prog.is_alive()
    finally:
        prog.terminate()
        prog.process.wait(timeout=5)
    assert not prog.is_alive()


# ---------------- 三种定位方式 ---------------- #
def test_locate_by_title_hit_and_miss():
    win = WindowInfo("1", "住院管理系统", 0, 0, 800, 600, 1234)
    cap = FakeCapturer([win])
    ok = resolve_target_window(cap, mode="title", title_pattern=".*住院.*")
    assert ok.window is win and ok.method == "title"
    miss = resolve_target_window(cap, mode="title", title_pattern="不存在XXX")
    assert miss.window is None and miss.method == "none"


def test_locate_active():
    win = WindowInfo("9", "HIS 主窗口", 10, 20, 1000, 700, 4321)
    cap = FakeCapturer([win], active=win)
    r = resolve_target_window(cap, mode="active")
    assert r.window is win and r.method == "active"
    assert resolve_target_window(FakeCapturer(), mode="active").window is None


def test_locate_launch_bind_by_pid():
    prog = launch_program("/bin/sleep", "20")
    try:
        # 模拟该进程启动后出现了一个属于它的窗口
        win = WindowInfo(str(prog.pid), "HIS", 0, 0, 800, 600, prog.pid)
        cap = FakeCapturer([win], active=win)
        r = resolve_target_window(cap, mode="launch",
                                  program_path="/bin/sleep",
                                  program_args="20", launch_wait_s=3,
                                  sleep=lambda _s: None,
                                  launcher=lambda p, a, w=None: prog)
        assert r.window is win and r.method == "pid"
    finally:
        prog.terminate()
        prog.process.wait(timeout=5)


def test_locate_launch_bad_path():
    cap = FakeCapturer()
    with pytest.raises(FileNotFoundError):
        resolve_target_window(cap, mode="launch", program_path="/no/such/bin",
                              sleep=lambda _s: None)


def test_locate_launch_process_exits(tmp_path):
    cap = FakeCapturer()  # 没有任何窗口
    r = resolve_target_window(cap, mode="launch",
                              program_path="/bin/false",
                              launch_wait_s=2, sleep=lambda _s: None)
    assert r.window is None
    assert r.method == "none"
    assert "已退出" in r.message
