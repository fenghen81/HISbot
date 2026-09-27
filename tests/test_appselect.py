"""“选择 HIS 应用程序”纯逻辑与向导回填测试。"""
import os

import pytest

from hisbot.core.types import WindowInfo
from hisbot.platform import appselect as A


def win(title, pid, path):
    return WindowInfo(str(pid), title, 0, 0, 800, 600, pid), path


def test_build_candidates_groups_by_exe_and_picks_title():
    w1, p1 = win("住院管理系统 - 首页", 100, "/opt/his/HisClient")
    w2, _ = win("住院管理系统 - 报表导出", 100, p1)   # 同进程多窗口、同路径
    w3, p3 = win("记事本", 200, "/usr/bin/notepad")
    paths = {100: p1, 200: p3}

    def path_for(pid):
        return paths.get(pid, "")

    cands = A.build_candidates([w1, w2, w3], path_for)
    his = [c for c in cands if c.exe_name.lower() == "hisclient"]
    assert len(his) == 1
    c = his[0]
    assert c.window_count == 2
    assert c.title == "住院管理系统 - 报表导出"   # 取更长标题
    assert c.is_his_like is True
    # 疑似 HIS 排在记事本前面
    assert cands[0] is c


def test_build_candidates_ignores_no_path_and_blank_title():
    w1, _ = win("", 1, r"C:\x.exe")                 # 无标题
    w2 = WindowInfo("2", "无路径窗口", 0, 0, 10, 10, 2)  # pid 取不到路径
    cands = A.build_candidates([w1, w2], lambda _pid: "")
    assert cands == []


def test_build_candidates_posix_grouping(tmp_path):
    exe = tmp_path / "his"
    exe.write_text("x")
    a = WindowInfo("1", "医生工作站", 0, 0, 10, 10, 300)
    b = WindowInfo("2", "文档", 0, 0, 10, 10, 301)
    cands = A.build_candidates([a, b], lambda pid: str(exe) if pid == 300
                               else "/usr/bin/less")
    names = [c.exe_name for c in cands]
    assert "his" in names and "less" in names
    assert cands[0].exe_name == "his"     # 医生工作站 → 疑似 HIS 置顶


def test_derive_title_pattern_is_regex_safe():
    rx = A.derive_title_pattern("住院管理 (V2.0)")
    assert rx == r"住院管理\s+\(V2\.0\)"
    import re
    assert re.search(rx, "住院管理 (V2.0) - 首页")
    assert A.derive_title_pattern("  ") == ""


def test_derive_title_pattern_spaces_loose():
    rx = A.derive_title_pattern("HIS   住院")
    assert rx == r"HIS\s+住院"
    import re
    assert re.search(rx, "HIS 住院")


def test_title_pattern_preview():
    pv = A.title_pattern_preview("住院管理系统 V10 - 张三的窗口")
    # 提取中文段与字母数字段，转义并用 | 连接
    assert "住院管理系统" in pv
    assert "V10" in pv


@pytest.mark.parametrize("mode,extra", [
    ("launch", dict(program_path=r"C:\HIS\His.exe", program_args="--p",
                    title_pattern=r"HIS", launch_wait_s=12)),
    ("active", dict(title_pattern="HIS")),
    ("title", dict(title_pattern=r".*HIS.*")),
])
def test_apply_window_choice_modes(mode, extra):
    site = {}
    A.apply_window_choice(site, mode, **extra)
    node = site["site"]
    assert node["locate_mode"] == mode
    assert node["setup_done"] is True
    if mode == "launch":
        assert node["program_path"] == r"C:\HIS\His.exe"
        assert node["program_args"] == "--p"
        assert node["launch_wait_s"] == 12


def test_apply_window_choice_bad_mode_falls_back():
    node = A.apply_window_choice({}, "weird", title_pattern="X")
    assert node["locate_mode"] == "title"


def test_is_setup_complete_flags():
    assert A.is_setup_complete({"site": {"setup_done": True}})
    assert A.is_setup_complete({"site": {"setup_dismissed": True}})
    assert not A.is_setup_complete({"site": {"locate_mode": "title",
                                            "window_title_pattern": ".*HIS.*"}})
    assert not A.is_setup_complete({"site": {}})
    # apply 后置位 setup_done
    s = {}
    A.apply_window_choice(s, "active")
    assert A.is_setup_complete(s)
