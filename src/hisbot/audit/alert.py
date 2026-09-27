"""告警管理（文档 7.4 / t_alert）：危险拦截、连续失败、看门狗超时等。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

from collections.abc import Callable
from dataclasses import dataclass

from ..core.util import now_iso


@dataclass
class Alert:
    severity: str
    error_code: str
    message: str
    job_run_id: str = ""
    snapshot: str = ""
    ts: str = ""
    id: int = 0


class AlertManager:
    # severity: INFO / WARN / ERROR / CRITICAL
    def __init__(self, repo=None, logger=None,
                 sink: Callable[[Alert], None] | None = None):
        self.repo = repo
        self.logger = logger
        self.sink = sink

    def raise_alert(self, severity: str, code: str, message: str, *,
                    job_run_id: str = "", snapshot: str = "") -> Alert:
        alert = Alert(severity, code, message, job_run_id, snapshot,
                      now_iso())
        if self.repo is not None:
            try:
                alert.id = self.repo.add_alert({
                    "job_run_id": job_run_id, "ts": alert.ts,
                    "severity": severity, "error_code": code,
                    "message": message, "snapshot": snapshot})
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
        if self.logger is not None:
            try:
                self.logger.error(message, code, state=None,
                                  snapshot_path=snapshot)
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
        if self.sink is not None:
            try:
                self.sink(alert)
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
        return alert

    def unacked(self):
        if self.repo is None:
            return []
        return self.repo.query_alerts(acknowledged=0)

    def ack(self, alert_id: int, by: str = "operator"):
        if self.repo is not None:
            self.repo.db.execute(
                "UPDATE t_alert SET acknowledged=1,acknowledged_by=?,"
                "acknowledged_at=? WHERE id=?",
                (by, now_iso(), alert_id))
            self.repo.db.commit()
