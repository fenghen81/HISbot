"""首启向导的 offscreen GUI 冒烟（不弹窗、不依赖真实显示）。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hisbot.config.settings import load_yaml  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402

from hisbot.ui.setup_wizard import SetupWizard  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def qapp():
    global _app
    _app = QApplication.instance() or QApplication([])
    yield _app


class _Center:
    def __init__(self, out):
        self.out = out

    def resolve(self, p):
        # 向导写 config/site.yaml；测试里直接落到临时文件
        return str(self.out / "site.yaml")


class _Repo:
    def __init__(self):
        self.calls = []

    def audit(self, *a, **k):
        self.calls.append((a, k))


class _C:
    def __init__(self, out):
        self.site = {"site": {}}
        self.center = _Center(out)
        self.repo = _Repo()
        self.reloaded = 0

    def reload_config(self):
        self.reloaded += 1


def test_wizard_confirm_launch(qapp, tmp_path):
    c = _C(tmp_path)
    dlg = SetupWizard(c)
    dlg._set_fields("launch", r"C:\HIS\HisClient.exe", "住院管理系统 登录")
    dlg.f_args.setText("--env prod")
    dlg._confirm()
    node = c.site["site"]
    assert node["locate_mode"] == "launch"
    assert node["program_path"] == r"C:\HIS\HisClient.exe"
    assert node["program_args"] == "--env prod"
    assert node["setup_done"] is True
    assert r"\ " not in node["window_title_pattern"]  # 空白已宽松化
    # 已落盘
    saved = load_yaml(str(tmp_path / "site.yaml"))
    assert saved["site"]["program_path"] == r"C:\HIS\HisClient.exe"
    assert c.reloaded == 1
    assert c.repo.calls and c.repo.calls[0][1]["object_type"] == "config"


def test_wizard_confirm_active_without_path(qapp, tmp_path):
    c = _C(tmp_path)
    dlg = SetupWizard(c)
    dlg._set_fields("active", "", "HIS 主窗口")
    dlg._confirm()
    node = c.site["site"]
    assert node["locate_mode"] == "active"
    assert node["setup_done"] is True
    assert node["window_title_pattern"] == r"HIS\s+主窗口"


def test_wizard_launch_requires_path(qapp, tmp_path):
    c = _C(tmp_path)
    dlg = SetupWizard(c)
    dlg._set_fields("launch", "", "某窗口")
    # 缺路径：不应写盘、不应 accept（弹警告框被 offscreen 自动关闭即可）
    QtWidgets.QMessageBox.warning = staticmethod(
        lambda *a, **k: QtWidgets.QMessageBox.Ok)
    dlg._confirm()
    assert "setup_done" not in c.site.get("site", {})
    assert not (tmp_path / "site.yaml").exists()
