"""platform.dirs 下载目录探测的纯逻辑测试。"""
import os

from hisbot.platform.dirs import (
    detect_downloads_dir,
    is_default_placeholder,
    pick_existing,
)


def test_pick_existing_picks_first_real_dir(tmp_path):
    exists = tmp_path / "dl"
    exists.mkdir()
    got = pick_existing([str(tmp_path / "nope"), str(exists), str(tmp_path / "x")])
    assert got == os.path.abspath(str(exists))


def test_pick_existing_none_when_none_exists(tmp_path):
    assert pick_existing([str(tmp_path / "a"), "", None, str(tmp_path / "b")]) is None


def test_is_default_placeholder():
    assert is_default_placeholder("")
    assert is_default_placeholder("./data/downloads")
    assert is_default_placeholder("data/downloads")
    assert is_default_placeholder("./data/downloads/")
    assert is_default_placeholder("")
    # 真实目录不算占位
    assert not is_default_placeholder(r"C:\Users\bot\Downloads")
    assert not is_default_placeholder("/home/bot/Downloads")


def test_detect_returns_str_or_none():
    res = detect_downloads_dir()
    assert res is None or isinstance(res, str)
