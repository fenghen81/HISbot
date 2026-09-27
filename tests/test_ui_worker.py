"""RunThread：与 RunControl 的控制联动、执行异常时的信号转发。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402

from hisbot.ui.worker import RunThread  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def qapp():
    global _app
    _app = QApplication.instance() or QApplication([])
    yield _app


class _FakeContainer:
    """run_job 直接抛错，走异常分支。"""

    def run_job(self, *a, **k):
        raise RuntimeError("模拟执行失败")


def test_control_pause_toggle_and_stop(qapp):
    t = RunThread(_FakeContainer(), {"job": {}}, "20260926")
    assert t.control.paused is False
    t.pause()
    assert t.control.paused is True        # 第一次请求暂停
    t.pause()
    assert t.control.paused is False       # 第二次恢复
    t.emergency_stop()
    assert t.control.aborted is True


def test_run_emits_error_on_exception(qapp):
    t = RunThread(_FakeContainer(), {"job": {}}, "20260926")
    logs, results = [], []
    t.log_appended.connect(lambda d: logs.append(d))
    t.finished_result.connect(lambda r: results.append(r))

    t.run()                                # 直接在当前线程跑异常分支

    assert logs[-1]["level"] == "ERROR" and "模拟执行失败" in logs[-1]["message"]
    assert results == [None]
