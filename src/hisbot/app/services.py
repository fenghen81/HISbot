"""依赖装配容器（五层架构的组合根 / composition root）。

主线程持有配置、库、日志、告警、看门狗、调度；真正的 OCR / 操作员在
执行工作线程内通过 build_* 工厂创建（RapidOCR 与 Xlib display 绑定创建线程）。
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger("hisbot")

from ..audit import AlertManager, StructuredLogger, Watchdog, save_snapshot
from ..config.center import ConfigCenter
from ..config.settings import load_yaml
from ..execute.context import RunControl
from ..execute.human import HumanSim
from ..execute.operator import HumanOperator
from ..parse import FileParser
from ..perception import ElementDetector, Locator, PageFingerprint, try_build_ocr
from ..platform import factory
from ..platform.windowing import resolve_target_window
from ..scan.classifier import ElementClassifier
from ..schedule import JobScheduler
from ..store.crypto import CryptoService
from ..store.database import Database
from ..store.repository import Repository


class Container:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.config_dir = os.path.join(self.root, "config")
        self.center = ConfigCenter(self.root)
        self.center.ensure_runtime_dirs()
        self.reload_config()

        # 凭据库 + 数据库主密钥
        self.vault = factory.create_credential_vault(self.config_dir)
        self.crypto = CryptoService(self._master_key_b64())

        # 存储
        self.db = Database(str(self.center.db_path))
        self.db.init_schema()
        self.repo = Repository(self.db, self.crypto)

        # 审计 / 告警 / 看门狗
        day = datetime.now().strftime("%Y%m%d")
        log_path = os.path.join(self.center.log_dir, f"ops-{day}.jsonl")
        self.logger = StructuredLogger(str(log_path), self.repo)
        self.alerts = AlertManager(self.repo, self.logger, None)
        self.watchdog = Watchdog(
            timeout_s=180, check_s=10,
            on_timeout=self._on_watchdog_timeout)
        self._active_control: RunControl | None = None
        self._active_operator = None

        # 调度
        self.scheduler = JobScheduler(self._scheduled_execute,
                                      self.logger, self.alerts)
        self.scheduler.start()
        self.parser = FileParser()
        self.logger.info("应用装配完成", "SYS-001")

    # ------------------------------------------------------------------ #
    def reload_config(self):
        self.app = load_yaml(self.center.resolve("config/app.yaml"))
        self.site = load_yaml(self.center.resolve("config/site.yaml"))
        self.kw = load_yaml(self.center.resolve("config/keywords.yaml"))

    # ---- 主密钥（文件权限 600；可由信息科替换托管）---- #
    def _master_key_b64(self) -> str:
        p = Path(self.config_dir) / "master.key"
        if p.exists():
            return p.read_text(encoding="ascii").strip()
        b64 = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        p.write_text(b64, encoding="ascii")
        try:
            os.chmod(p, 0o600)
        except Exception:
            _log.warning("设置 master.key 权限 600 失败", exc_info=True)
        return b64

    # ---- 凭据 ---- #
    def set_credential(self, account: str, password: str):
        self.vault.save("his_account", account)
        self.vault.save("his_password", password)

    def get_credential(self) -> tuple[str, str]:
        return (self.vault.load("his_account") or "",
                self.vault.load("his_password") or "")

    def vault_backend(self) -> str:
        try:
            return self.vault.backend()
        except Exception:
            return "unknown"

    # ---- 环境校验 ---- #
    def check_environment(self):
        scale = self.site.get("scale", {})
        res = scale.get("expected_resolution") or [1920, 1080]
        return factory.check_display_environment(
            float(scale.get("expected_ratio", 1.0)),
            (int(res[0]), int(res[1])),
            scale.get("mismatch_policy", "abort"))

    # ---- 工作线程内：感知 ---- #
    def build_perception(self):
        ocr = try_build_ocr()
        locator = Locator(ocr)
        fp = PageFingerprint(ocr)
        detector = ElementDetector(ocr)
        kw = self.kw
        classifier = ElementClassifier(
            list(kw.get("blacklist_keywords", [])),
            list(kw.get("export_keywords", [])),
            list(kw.get("back_keywords", [])),
            list(kw.get("nav_safe_keywords", [])))
        return ocr, locator, fp, detector, classifier

    # ---- 工作线程内：真实操作员 ---- #
    def build_real_operator(self, control: RunControl, *,
                            window_message=None):
        capturer = factory.create_capturer()
        injector = factory.create_input()
        scfg = self.site.get("site", {})
        mode = scfg.get("locate_mode", "title")
        pattern = scfg.get("window_title_pattern", ".*HIS.*")
        result = resolve_target_window(
            capturer, mode=mode, title_pattern=pattern,
            program_path=scfg.get("program_path", ""),
            program_args=scfg.get("program_args", ""),
            work_dir=scfg.get("work_dir", ""),
            launch_wait_s=float(scfg.get("launch_wait_s", 8) or 8))
        self._launched_program = result.launched
        if window_message is not None:
            window_message.append(result.message)
        if result.window is not None:
            hwid = result.window.hwid
            self.logger.info(
                result.message, code="WIN-OK", locate=result.method,
                hwid=hwid, title=result.window.title, pid=result.window.pid)
        else:
            # 未绑定具体窗口：退化为全屏捕获，并明确告警，避免误点其它窗口
            hwid = "root"
            msg = "未能绑定 HIS 窗口，已退化为全屏操作：" + result.message
            self.logger.warn(msg, code="WIN-NONE", locate=result.method)
            try:
                self.alerts.raise_alert("warning", "WIN-NONE", msg)
            except Exception:
                _log.warning("上报告警 WIN-NONE 失败", exc_info=True)
        human = HumanSim(injector, is_abort=lambda: control.aborted)
        op = HumanOperator(capturer, injector, human, hwid)
        op.hwid = hwid
        return op

    # ------------------------------------------------------------------ #
    def run_job(self, job_cfg: dict, biz_date: str, *, control: RunControl,
                observer=None, sim=False, sim_kwargs=None,
                on_operator=None):
        """在调用线程（执行工作线程）内完成一次作业。"""
        from ..execute.engine import ExecEngine
        from ..simulator.headless import SimHis
        operator: Any = None
        if sim:
            kw = {"watch_dir": str(self.center.watch_dir),
                  "report_date": biz_date_fmt(biz_date)}
            kw.update(sim_kwargs or {})
            operator = SimHis(**kw)  # type: ignore[arg-type]
        else:
            operator = self.build_real_operator(control)
        self._active_operator = operator
        self._active_control = control
        if on_operator:
            on_operator(operator)

        _ocr, locator, fp, _det, _cls = self.build_perception()
        timing = self.app.get("timing", {})
        dl = dict(self.app.get("download", {}))
        engine = ExecEngine(
            operator=operator, locator=locator, fp=fp,
            config_dir=self.config_dir, parser=self.parser,
            repo=self.repo, crypto=self.crypto,
            danger_words=list(self.kw.get("blacklist_keywords", [])),
            completion_keywords=list(
                self.app.get("download", {}).get("completion_keywords", [])),
            download_cfg=dl, control=control, observer=observer,
            settle_secs=max(0.05, int(timing.get("page_load_timeout_ms",
                                                  10000)) / 1000.0 * 0.1),
            nav_timeout_s=int(timing.get("page_load_timeout_ms",
                                         10000)) / 1000.0 * 4,
            ocr_min=float(self.kw.get("matching", {})
                          .get("ocr_min_confidence", 0.75)))
        user, pwd = self.get_credential()
        self.watchdog.start()
        try:
            result = engine.run(
                job_cfg, username=user, password=pwd, biz_date=biz_date,
                watch_dir=str(self.center.watch_dir),
                archive_dir=str(self.center.archive_dir),
                quarantine_dir=str(self.center.quarantine_dir))
        finally:
            self.watchdog.stop()
            self._active_operator = None
        return result

    def _scheduled_execute(self, job_cfg):
        from datetime import date
        control = RunControl()
        return self.run_job(job_cfg, date.today().strftime("%Y%m%d"),
                            control=control)

    # ------------------------------------------------------------------ #
    def _on_watchdog_timeout(self):
        if self._active_control:
            try:
                self._active_control.emergency_stop()
            except Exception:
                _log.warning("看门狗触发紧急停止失败", exc_info=True)
        snap = ""
        try:
            frame = None
            if self._active_operator is not None:
                frame = self._active_operator.capture()
            snap = save_snapshot(str(self.center.snapshot_dir),
                                 frame=frame, state="WATCHDOG",
                                 prefix="watchdog")
        except Exception:
            _log.warning("看门狗现场快照保存失败", exc_info=True)
        self.alerts.raise_alert("CRITICAL", "SYS-002",
                                "执行线程 3 分钟无心跳，已安全停止",
                                snapshot=snap)

    def shutdown(self):
        try:
            self.scheduler.shutdown()
        except Exception:
            _log.warning("调度器关闭异常", exc_info=True)
        try:
            self.watchdog.stop()
        except Exception:
            _log.warning("看门狗停止异常", exc_info=True)


def biz_date_fmt(s: str) -> str:
    """20260922 → 2026-09-22；已带分隔符原样返回。"""
    s = str(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s
