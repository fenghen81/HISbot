"""定时调度：工作时间窗、单执行槽互斥、cron 注册校验。"""
import time
from datetime import datetime

from hisbot.schedule.scheduler import JobScheduler, _in_window


class _Log:
    def __init__(self):
        self.ev = []

    def info(self, *a, **k):
        self.ev.append(("info", a))

    def warn(self, *a, **k):
        self.ev.append(("warn", a))

    def error(self, *a, **k):
        self.ev.append(("error", a))


def _at(h, m):
    return datetime(2026, 9, 23, h, m)


def test_time_window():
    assert _in_window("", _at(3, 0)) is True
    assert _in_window("08:00-18:00", _at(9, 0)) is True
    assert _in_window("08:00-18:00", _at(20, 0)) is False
    assert _in_window("22:00-06:00", _at(23, 0)) is True
    assert _in_window("22:00-06:00", _at(12, 0)) is False


def _job(jid="j1", cron="0 8 * * *", window=""):
    return {"job": {"job_id": jid,
                    "schedule": {"enabled": True, "cron": cron,
                                 "time_window": window}}}


def test_executor_slot_mutex_and_window():
    def slow(_job_cfg):
        time.sleep(0.4)
        return type("R", (), {"success": True, "error_code": ""})()

    s = JobScheduler(slow, _Log())
    s.start()
    job = _job()
    assert s.register(job) and s.job_ids() == ["j1"]
    # 占用唯一执行槽时，并发触发应跳过而非堆积
    assert s._run_lock.acquire()
    skipped = s._trigger(job)
    assert skipped.skipped and skipped.reason == "executor_busy"
    s._run_lock.release()
    assert s._trigger(job).ok
    # 时间窗外跳过
    outside = _job("j2", window="00:00-00:01")
    r = s._trigger(outside)
    assert r.skipped and r.reason == "outside_window"
    s.shutdown()


def test_disabled_and_bad_cron():
    s = JobScheduler(lambda c: None, _Log())
    s.start()
    disabled = {"job": {"job_id": "x", "schedule": {"enabled": False,
                                                    "cron": "0 8 * * *"}}}
    assert s.register(disabled) is False
    import pytest
    with pytest.raises(ValueError):
        s.register(_job("bad", cron="not-a-cron"))
    s.shutdown()
