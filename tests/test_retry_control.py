"""重试策略（表 14）与运行控制（暂停/单步/急停）测试。"""
import threading
import time

import pytest

from hisbot.core.errors import AbortedByUser
from hisbot.execute.context import RunControl
from hisbot.execute.retry import RetryPolicy

NO_RETRY = ["PRS-001", "PRS-002", "EXE-001", "EXE-002", "DLD-004",
            "DLD-006", "DLD-007", "SCN-001", "SCN-003", "SYS-000"]


@pytest.mark.parametrize("code", NO_RETRY)
def test_fatal_and_security_codes_never_retry(code):
    assert RetryPolicy().decide(code, 0).retry is False


def test_locate_retry_backoff_1_2_4():
    p = RetryPolicy()
    assert [p.decide("DET-001", i).backoff_s for i in range(3)] == [1, 2, 4]
    assert p.decide("DET-001", 3).retry is False


def test_download_retry_backoff_5_10():
    p = RetryPolicy()
    assert [p.decide("DLD-001", i).backoff_s for i in range(2)] == [5, 10]
    assert p.decide("DLD-001", 2).retry is False


def test_pause_resume_gate():
    rc = RunControl()
    rc.request_pause()
    threading.Timer(0.3, rc.resume).start()
    t0 = time.time()
    rc.gate()
    assert time.time() - t0 >= 0.25


def test_single_step_blocks_until_permit():
    rc = RunControl()
    rc.enable_step_mode()
    # 第一次动作边界：阻塞到 step_once
    threading.Timer(0.3, rc.step_once).start()
    t0 = time.time()
    rc.gate()
    assert time.time() - t0 >= 0.25
    # 第二次动作边界：无新许可，应继续阻塞
    done = threading.Event()
    threading.Thread(target=lambda: (rc.gate(), done.set())).start()
    time.sleep(0.25)
    assert not done.is_set()
    rc.disable_step_mode()
    assert done.wait(0.5)


def test_emergency_stop_aborts_and_releases():
    rc = RunControl()
    rc.enable_step_mode()
    threading.Timer(0.2, rc.emergency_stop).start()
    with pytest.raises(AbortedByUser):
        rc.gate()
    assert rc.aborted
