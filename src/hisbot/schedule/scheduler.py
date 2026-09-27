from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import time as dtime

from ..core.util import now_iso


@dataclass
class ScheduledRun:
    job_id: str
    started_at: str
    ok: bool = False
    skipped: bool = False
    reason: str = ""


def _in_window(window: str, now: datetime | None = None) -> bool:
    """window 形如 '08:00-18:00'；空串表示全天。"""
    if not window or "-" not in window:
        return True
    now = now or datetime.now()
    try:
        a, b = window.split("-", 1)
        ta = dtime.fromisoformat(a.strip())
        tb = dtime.fromisoformat(b.strip())
        cur = now.time().replace(second=0, microsecond=0)
        if ta <= tb:
            return ta <= cur <= tb
        return cur >= ta or cur <= tb      # 跨零点窗口
    except Exception:
        return True


class JobScheduler:
    def __init__(self, execute_fn: Callable[[dict], object],
                 logger=None, alert=None):
        """execute_fn(job_cfg)->ExecResult，在调度工作线程被调用。"""
        from apscheduler.schedulers.background import BackgroundScheduler
        self._sched = BackgroundScheduler(daemon=True,
                                          job_defaults={"coalesce": True,
                                                        "max_instances": 1,
                                                        "misfire_grace_time":
                                                        600})
        self.execute_fn = execute_fn
        self.logger = logger
        self.alert = alert
        self._run_lock = threading.Lock()       # 全局单执行槽
        self._jobs: dict[str, dict] = {}

    # ------------------------------------------------------------------ #
    def register(self, job_cfg: dict) -> bool:
        job = job_cfg.get("job", job_cfg)
        sch = job.get("schedule", {})
        jid = job["job_id"]
        if not sch.get("enabled"):
            return False
        cron = sch.get("cron", "")
        if not cron:
            return False
        parts = cron.split()
        if len(parts) != 5:
            raise ValueError(f"作业 {jid} cron 必须是 5 段：{cron}")
        m, h, dom, mon, dow = parts
        if jid in self._jobs:
            self._sched.remove_job(jid)
        self._sched.add_job(self._trigger, "cron", id=jid,
                            minute=m, hour=h, day=dom, month=mon,
                            day_of_week=dow, args=[job_cfg],
                            replace_existing=True)
        self._jobs[jid] = job_cfg
        if self.logger:
            self.logger.info(f"已注册定时作业 {jid}（{cron}）", "SCH-001")
        return True

    def unregister(self, job_id: str):
        if job_id in self._jobs:
            self._sched.remove_job(job_id)
            self._jobs.pop(job_id, None)

    def run_now(self, job_cfg: dict):
        threading.Thread(target=self._trigger, args=(job_cfg,),
                         daemon=True, name="manual-run").start()

    def start(self):
        if not self._sched.running:
            self._sched.start()

    def shutdown(self):
        if self._sched.running:
            self._sched.shutdown(wait=False)

    def job_ids(self):
        return list(self._jobs.keys())

    # ------------------------------------------------------------------ #
    def _trigger(self, job_cfg: dict) -> ScheduledRun:
        job = job_cfg.get("job", job_cfg)
        jid = job["job_id"]
        window = job.get("schedule", {}).get("time_window", "")
        run = ScheduledRun(jid, now_iso())
        if not _in_window(window):
            run.skipped = True
            run.reason = "outside_window"
            if self.logger:
                self.logger.warn(f"作业 {jid} 不在工作时间窗 {window}，跳过",
                                 "SCH-002")
            return run
        # 单执行槽：另一作业正在跑则本次跳过（不堆积）
        if not self._run_lock.acquire(blocking=False):
            run.skipped = True
            run.reason = "executor_busy"
            if self.logger:
                self.logger.warn(f"执行槽占用，作业 {jid} 本次跳过",
                                 "SCH-003")
            return run
        try:
            res = self.execute_fn(job_cfg)
            run.ok = bool(getattr(res, "success", False))
            if not run.ok:
                run.reason = getattr(res, "error_code", "FAILED")
                if self.alert:
                    self.alert.raise_alert(
                        "ERROR", run.reason,
                        f"定时作业 {jid} 执行失败：{getattr(res,'message','')}")
        except Exception as e:  # noqa: BLE001
            run.reason = "EXCEPTION"
            if self.logger:
                self.logger.error(f"定时作业 {jid} 异常：{e}", "SYS-000")
            if self.alert:
                self.alert.raise_alert("CRITICAL", "SYS-000",
                                       f"定时作业 {jid} 异常：{e}")
        finally:
            self._run_lock.release()
        return run
