"""执行引擎主状态机（文档 4.5 / 表 13 / 表 14）。

消费“已审核签发”的作业配置，驱动：
INIT(签名校验) → LOGIN → NAVIGATE(三级定位/指纹到达) → TARGET(前置+导出)
→ DOWNLOAD(双信号与门) → PARSE → PERSIST(脱敏加密/幂等) → DONE；
失败进入 RETRY 按表 14 退避，致命/不可恢复转 FAILED，急停转 ABORTED。
任何动作前过 RunControl 检查点（暂停 / 单步 / 急停）。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import os
import time
from dataclasses import dataclass, field

from ..config.settings import load_yaml
from ..config.signing import verify_job
from ..core.errors import (
    AbortedByUser,
    ArchiveMoveError,
    BatchRollbackError,
    DbLockError,
    DownloadTimeoutError,
    ElementNotFoundError,
    HisBotError,
    LoginError,
    MagicMismatchError,
    NavigationTimeoutError,
    UnapprovedPathError,
    WatchDirError,
)
from ..core.types import State
from ..core.util import now_iso
from ..download import DownloadCoordinator
from ..parse import FileParser
from ..perception.download_signal import DownloadSignalDetector
from ..perception.textutil import normalize_text
from .context import RunControl
from .retry import RetryPolicy


@dataclass
class ExecResult:
    success: bool
    state: str
    run_id: str = ""
    files: list[str] = field(default_factory=list)
    rows_inserted: int = 0
    rows_updated: int = 0
    error_code: str | None = None
    message: str = ""


class ExecObserver:
    def on_state(self, state: str, **kw): ...
    def on_log(self, level: str, message: str, code: str = ""): ...
    def on_step(self, seq: int, state: str, action: str,
                target: str, result: str): ...
    def on_target(self, text: str, rect: tuple, state: str): ...
    def heartbeat(self): ...


class ExecEngine:
    REACHED = 0.85

    def __init__(self, *, operator, locator, fp,
                 config_dir: str,
                 parser: FileParser | None = None,
                 repo=None, crypto=None,
                 danger_words: list[str],
                 completion_keywords: list[str],
                 download_cfg: dict,
                 control: RunControl,
                 retry: RetryPolicy | None = None,
                 observer: ExecObserver | None = None,
                 settle_secs: float = 1.2,
                 nav_timeout_s: float = 10.0,
                 ocr_min: float = 0.75,
                 sleep=time.sleep):
        self.op = operator
        self.locator = locator
        self.fp = fp
        self.config_dir = config_dir
        self.parser = parser or FileParser()
        self.repo = repo
        self.crypto = crypto
        self.danger_words = [normalize_text(w) for w in danger_words]
        self.completion_kw = completion_keywords
        self.dl_cfg = download_cfg
        self.control = control
        self.retry = retry or RetryPolicy()
        self.obs = observer or ExecObserver()
        self.settle = settle_secs
        self.nav_timeout = nav_timeout_s
        self.ocr_min = ocr_min
        self.sleep = sleep
        self.state = State.IDLE.value
        self.run_id = ""
        self._seq = 0

    # ================================================================== #
    def run(self, job_cfg: dict, *, username: str, password: str,
            biz_date: str, watch_dir: str | None = None,
            archive_dir: str | None = None,
            quarantine_dir: str | None = None) -> ExecResult:
        # INIT：签名校验（EXE-002）------------------------------------- #
        job = job_cfg.get("job", job_cfg)
        verify_job(job_cfg, raise_on_fail=True)
        if not job.get("path"):
            raise UnapprovedPathError("作业配置缺少审核通过的导航路径")
        safety = job.get("safety", {})
        if not all(s.get("approved") for s in job["path"]) and \
                not safety.get("allow_unapproved_path", False):
            raise UnapprovedPathError("导航路径存在未批准步骤 EXE-001")

        total = len(job["path"]) + 4
        if self.repo:
            self.repo.upsert_job({
                "job_id": job["job_id"], "job_name": job.get("job_name"),
                "site_id": job.get("site_id"),
                "graph_version": job.get("graph_version"),
                "entry_page_id": job["path"][0].get("page", ""),
                "target_page_id": job.get("target", {}).get("page_id", ""),
                "path_element_ids": [s.get("element") or s.get("text")
                                     for s in job["path"]],
                "export_keywords": job.get("target", {})
                .get("button_keywords", []),
                "download_expect": job.get("download", {})
                .get("expect_files", 1),
                "schedule_cron": job.get("schedule", {}).get("cron", ""),
                "status": job.get("status", "reviewed"),
                "reviewed_by": job.get("reviewed_by", ""),
                "reviewed_at": job.get("reviewed_at", ""),
                "config_version": job.get("config_version", 1),
                "config_hash": job.get("config_hash", "")})
            self.run_id = self.repo.start_run(
                job["job_id"], total, username)
        self._dirs = self._resolve_dirs(job, watch_dir, archive_dir,
                                        quarantine_dir)
        self._set(State.INIT.value)
        try:
            # LOGIN ---------------------------------------------------- #
            self._login(username, password)

            # NAVIGATE ------------------------------------------------- #
            self._navigate(job["path"])

            # TARGET + EXPORT + DOWNLOAD（可重试单元）------------------ #
            dl = self._target_export_download(job, biz_date)

            # PARSE + PERSIST ------------------------------------------ #
            ins, upd = self._parse_and_persist(job, dl, biz_date)

            # DONE ----------------------------------------------------- #
            self._set(State.DONE.value)
            if self.repo:
                self.repo.finish_run(self.run_id, "success",
                                     State.DONE.value,
                                     files=len(dl.archived), rows=ins + upd)
                self.repo.audit(username, "job_run_success",
                                object_type="job", object_id=job["job_id"],
                                detail=f"files={len(dl.archived)} "
                                       f"inserted={ins} updated={upd}")
            return ExecResult(True, State.DONE.value, self.run_id,
                              dl.files, ins, upd,
                              message="作业执行成功")
        except AbortedByUser as e:
            self._finalize_fail(State.ABORTED.value, e)
            return ExecResult(False, State.ABORTED.value, self.run_id,
                              error_code=e.code, message="操作员急停，已中止")
        except HisBotError as e:
            self._finalize_fail(State.FAILED.value, e)
            return ExecResult(False, State.FAILED.value, self.run_id,
                              error_code=e.code, message=str(e))
        except Exception as e:  # noqa: BLE001
            err = HisBotError(str(e))
            self._finalize_fail(State.FAILED.value, err)
            return ExecResult(False, State.FAILED.value, self.run_id,
                              error_code="SYS-000", message=str(e))

    # ================================================================== #
    # LOGIN
    # ================================================================== #
    def _login(self, username: str, password: str):
        self._set(State.LOGIN.value)
        for attempt in range(6):
            self.control.gate()
            frame = self.op.capture()
            acc = self._find(frame, ["用户名", "账号", "用户编码", "工号"])
            login_btn = self._find(frame, ["登录", "登 录", "确定"])
            if acc is None and login_btn is None:
                self._log("INFO", "检测到已处于登录态，跳过登录")
                return
            if acc is None:
                # 无账号框但有登录按钮：异常登录页
                if attempt >= 2:
                    raise LoginError("登录页未找到账号输入框")
                self.sleep(1)
                continue
            prev = self.fp.compute(frame)
            self.op.click_rect(acc.box)
            self.op.type_text(username)
            frame2 = self.op.capture()
            pwd = self._find(frame2, ["密码"])
            if pwd is not None:
                self.op.click_rect(pwd.box)
                self.op.type_text(password)
            btn = self._find(self.op.capture(),
                             ["登录", "登 录", "确定"]) or login_btn
            self.op.click_rect(btn.box)
            self._wait_change(prev, expect_change=True)
            # 确认离开登录页
            check = self.op.capture()
            if self._find(check, ["用户名", "账号", "用户编码", "工号"]) \
                    is None:
                self._log("INFO", "登录成功")
                return
            if attempt >= 2:
                raise LoginError("登录后仍停留在登录页，账号口令或验证码异常")
            self.sleep(self.retry.decide("LOG-001", attempt).backoff_s or 1)
        raise LoginError("登录失败次数超限 LOG-001")

    # ================================================================== #
    # NAVIGATE
    # ================================================================== #
    def _navigate(self, steps: list[dict]):
        self._set(State.NAVIGATE.value)
        for _i, step in enumerate(steps, 1):
            text = step["text"]
            manual = self._center_rel(step.get("rel_bbox"))
            for attempt in range(4):
                self.control.gate()
                frame = self.op.capture()
                prev = self.fp.compute(frame)
                try:
                    loc = self._locate(frame, [text], manual_rel=manual,
                                       label=f"导航「{text}」")
                except ElementNotFoundError:
                    dec = self.retry.decide("DET-001", attempt)
                    if not dec.retry:
                        raise
                    self._log("WARN", f"未定位「{text}」，"
                                      f"{dec.backoff_s}s 后重试", "DET-001")
                    self.sleep(dec.backoff_s)
                    continue
                self.obs.on_target(text, (loc.rect.x, loc.rect.y,
                                          loc.rect.w, loc.rect.h),
                                   State.NAVIGATE.value)
                self.op.click_rect(loc.rect)
                try:
                    self._wait_change(prev, expect_change=True)
                except NavigationTimeoutError:
                    dec = self.retry.decide("EXE-004", attempt)
                    if not dec.retry:
                        raise
                    self._log("WARN", f"点击「{text}」页面未跳转，"
                                      f"{dec.backoff_s}s 后重走", "EXE-004")
                    self.sleep(dec.backoff_s)
                    continue
                self._add_step(State.NAVIGATE.value, "click", text,
                               "success", step.get("page", ""))
                break
            else:
                raise NavigationTimeoutError(
                    f"导航至「{text}」多次重试仍失败 EXE-004")

    # ================================================================== #
    # TARGET + EXPORT + DOWNLOAD
    # ================================================================== #
    def _target_export_download(self, job: dict, biz_date: str):
        from ..download.coordinator import CaptureResult
        self._set(State.TARGET.value)
        target = job["target"]
        # 前置动作（日期范围等），全部经定位与危险拦截
        for act in target.get("pre_actions", []):
            self.control.gate()
            kind = act.get("type")
            if kind == "wait":
                self.sleep(int(act.get("ms", 0)) / 1000.0)
                continue
            frame = self.op.capture()
            loc = self._locate(frame, [act.get("text", "")],
                               label=f"前置「{act.get('text')}」")
            self.obs.on_target(act.get("text", ""),
                               (loc.rect.x, loc.rect.y, loc.rect.w,
                                loc.rect.h), State.TARGET.value)
            self.op.click_rect(loc.rect)
            if kind == "input" and act.get("value"):
                self.op.type_text(str(act["value"]))

        btn_keywords = list(dict.fromkeys(
            target.get("button_keywords", []) +
            ([target.get("button_text")] if target.get("button_text")
             else [])))
        manual_btn = self._center_rel(target.get("button_rel_bbox"))
        dl_cfg = job.get("download", {})
        expect = int(dl_cfg.get("expect_files", 1))
        pattern = dl_cfg.get("expect_name_pattern")
        timeout_ms = int(dl_cfg.get("timeout_ms", 120000))
        on_timeout = dl_cfg.get("on_timeout", "retry")

        attempt = 0
        while True:
            self._set(State.EXPORT.value)
            self.control.gate()
            frame = self.op.capture()
            self.fp.compute(frame)  # 导出定位前预热 OCR
            loc = self._locate(frame, btn_keywords, manual_rel=manual_btn,
                               label="导出按钮")
            self.obs.on_target(target.get("button_text", "导出"),
                               (loc.rect.x, loc.rect.y, loc.rect.w,
                                loc.rect.h), State.EXPORT.value)
            self.op.click_rect(loc.rect)
            self._add_step(State.EXPORT.value, "click_export",
                           target.get("button_text", "导出"), "clicked",
                           target.get("page_id", ""))
            started = time.time()
            self._set(State.DOWNLOAD.value)
            coord = self._new_coordinator()
            res: CaptureResult = coord.capture(
                job_name=job["job_name"] or job["job_id"],
                biz_date=biz_date, started_at=started,
                expect_files=expect, name_pattern=pattern,
                timeout_ms=timeout_ms,
                get_frame=self.op.capture,
                is_abort=lambda: self.control.aborted,
                is_paused=lambda: self.control.paused,
                log=lambda m: self._log("INFO", m))
            if res.success:
                self._log("INFO", res.message)
                return res
            # 失败分类与重试
            code = res.error_code or "DLD-001"
            self._log("WARN", f"{res.message}（{code}）", code)
            if code in ("DLD-004", "DLD-006", "DLD-007"):
                if code == "DLD-004":
                    raise MagicMismatchError("下载文件魔数校验失败 DLD-004")
                if code == "DLD-006":
                    raise ArchiveMoveError("归档移动失败 DLD-006")
                raise WatchDirError("下载目录不可用 DLD-007")
            if on_timeout == "fail":
                raise DownloadTimeoutError(
                    f"下载失败且配置为不重试（{code}）")
            dec = self.retry.decide("DLD-001", attempt)
            if not dec.retry:
                raise DownloadTimeoutError(f"下载重试耗尽（{code}）")
            self._set(State.RETRY.value)
            self._log("WARN", f"{dec.pre_action}，{dec.backoff_s}s 后重新导出",
                      code)
            self.sleep(dec.backoff_s)
            attempt += 1

    # ================================================================== #
    # PARSE + PERSIST
    # ================================================================== #
    def _parse_and_persist(self, job, dl, biz_date):
        mapping_ref = job.get("parse", {}).get("mapping")
        mapping_path = mapping_ref
        if mapping_ref and not os.path.isabs(mapping_ref):
            mapping_path = os.path.join(self.config_dir, mapping_ref)
        mapping_cfg = load_yaml(mapping_path) if mapping_ref else {}
        fm = mapping_cfg.get("field_mapping", mapping_cfg)
        table = fm.get("target_table", "t_report_record")
        key_cols = fm.get("business_key", ["report_date", "dept_code",
                                           "item_code"])
        specs = [{"target": c["target"], "encrypt": c.get("encrypt", False),
                  "mask_rule": c.get("mask_rule"),
                  "index_mode": c.get("index_mode")}
                 for c in fm.get("columns", []) if c.get("sensitive")]

        total_ins = total_upd = 0
        for idx, arch in enumerate(dl.archived):
            self._set(State.PARSE.value)
            self.control.gate()
            file_id = ""
            if self.repo:
                file_id = self.repo.register_export_file({
                    "file_id": f"file_{arch.sha256[:16]}",
                    "job_run_id": self.run_id,
                    "origin_name": dl.origins[idx],
                    "archived_path": arch.path,
                    "file_ext": os.path.splitext(arch.name)[1],
                    "file_size": arch.size, "sha256": arch.sha256,
                    "download_started_at": "", "download_finished_at":
                    now_iso(), "signal_prompt": int(dl.signal_prompt),
                    "signal_stable": int(dl.signal_stable),
                    "parse_status": "parsing"})
            pr = self.parser.parse(
                arch.path, mapping_cfg,
                derived={"file_id": file_id, "biz_date": biz_date})
            if self.repo:
                self.repo.add_parse_report(
                    file_id, pr.parser, pr.header_row_count,
                    pr.column_count, pr.total, pr.ok, pr.fail,
                    pr.detail, pr.confidence)
            if not pr.success:
                if self.repo:
                    self.repo.update_export_file(file_id,
                                                 parse_status="failed")
                # 表 14：解析失败不重试，转人工
                from ..core.errors import ParseRatioError
                raise ParseRatioError(
                    f"文件 {arch.name} 解析失败：{pr.fatal_message}")

            self._set(State.PERSIST.value)
            ins, upd = self._persist_with_retry(
                table, key_cols, specs, pr.mapped.rows, file_id)
            total_ins += ins
            total_upd += upd
            if self.repo:
                self.repo.update_export_file(file_id,
                                             parse_status="success")
        return total_ins, total_upd

    def _persist_with_retry(self, table, key_cols, specs, rows, file_id):
        if self.repo is None:
            return len(rows), 0
        import json as _json
        for attempt in range(4):
            self.control.gate()
            batch = self.repo.start_batch(file_id, table)
            now = now_iso()
            erows = []
            for i, r in enumerate(rows, 1):
                rr = dict(r)
                rr.update(file_id=file_id, batch_id=batch,
                          source_row_no=i, created_at=now, updated_at=now)
                if isinstance(rr.get("ext_data"), (dict, list)):
                    rr["ext_data"] = _json.dumps(rr["ext_data"],
                                                 ensure_ascii=False)
                erows.append(rr)
            ups = self.repo.upsert_batch(
                table, erows, key_cols, sensitive_specs=specs)
            if ups["failed"] == 0:
                self.repo.finish_batch(
                    batch, ups["total"], ups["inserted"],
                    ups["updated"], 0, "success")
                return ups["inserted"], ups["updated"]
            dec = self.retry.decide("DBS-001", attempt)
            self.repo.finish_batch(batch, ups["total"],
                                   ups["inserted"], ups["updated"],
                                   ups["failed"], "failed")
            if not dec.retry:
                raise BatchRollbackError(
                    f"入库失败行 {ups['failed']}：{ups['errors'][:1]}")
            self._log("WARN", f"入库冲突/锁，{dec.backoff_s}s 重试",
                      "DBS-001")
            self.sleep(dec.backoff_s)
        raise DbLockError("入库多次重试仍失败 DBS-001")

    # ================================================================== #
    # 感知 / 安全辅助
    # ================================================================== #
    def _find(self, frame, words):
        if not self.locator.ocr:
            return None
        res = self.locator.ocr.find_text(frame, words,
                                         min_score=self.ocr_min)
        return res[0] if res else None

    def _locate(self, frame, keywords, manual_rel=None, label="元素"):
        """L1 OCR（含危险文字拦截）→ 失败交由定位器模板/人工兜底。"""
        wd = self._find(frame, [w for w in keywords if w])
        if wd is not None:
            text = normalize_text(wd.text)
            # 三重只读之语义拦截：实际点中的文字含危险词，绝不点击
            if any(d in text for d in self.danger_words):
                raise UnapprovedPathError(
                    f"定位命中危险元素「{wd.text}」，已拦截 SCN-003")
            from ..perception.locator import Located
            return Located(wd.box.x + wd.box.w // 2,
                           wd.box.y + wd.box.h // 2,
                           "ocr", wd.score, wd.text, wd.box)
        loc = self.locator.locate(frame, keywords=keywords,
                                  manual_rel=manual_rel)
        if loc is None:
            raise ElementNotFoundError(f"{label} 三级定位均失败 DET-001")
        return loc

    def _wait_change(self, prev_fp, expect_change: bool = True):
        """点击后等待：页面相对点击前发生变化并稳定，否则导航超时。"""
        deadline = time.time() + self.nav_timeout
        confirmed = False
        while time.time() < deadline:
            self.control.gate()
            self.sleep(self.settle)
            cur = self.fp.compute(self.op.capture())
            sim = self.fp.similarity(cur, prev_fp.title, prev_fp.phash,
                                     prev_fp.anchors)
            changed = sim < self.REACHED
            if changed == expect_change:
                if confirmed:
                    return
                confirmed = True
                self.sleep(self.settle)
                continue
            confirmed = False
        raise NavigationTimeoutError("页面未在超时内到达预期状态 EXE-004")

    @staticmethod
    def _center_rel(rel):
        if not rel or len(rel) != 4:
            return None
        x, y, w, h = rel
        return (x + w / 2, y + h / 2)

    def _new_coordinator(self) -> DownloadCoordinator:
        d = self._dirs
        ocr = self.locator.ocr
        detector = DownloadSignalDetector(
            ocr, self.completion_kw,
            hit_frames=int(self.dl_cfg.get("completion_hit_frames", 2)))
        return DownloadCoordinator(
            d["watch"], d["archive"], d["quarantine"], detector,
            allowed_ext=tuple(self.dl_cfg.get(
                "allowed_ext", [".xlsx", ".xls", ".csv", ".pdf"])),
            temp_suffixes=tuple(self.dl_cfg.get(
                "temp_suffixes", [".crdownload", ".part", ".tmp"])),
            sample_interval_ms=int(self.dl_cfg.get(
                "stable_sample_interval_ms", 500)),
            sample_count=int(self.dl_cfg.get("stable_sample_count", 3)),
            exclusive_check=bool(self.dl_cfg.get("exclusive_open_check",
                                                 True)),
            magic_check=bool(self.dl_cfg.get("magic_check", True)))

    def _resolve_dirs(self, job, watch, archive, quarantine):
        cfg = self.dl_cfg

        def p(v, default):
            v = v or default
            return v if os.path.isabs(v) else os.path.abspath(v)
        return {"watch": p(watch, cfg.get("watch_dir", "./data/downloads")),
                "archive": p(archive, cfg.get("archive_dir",
                                              "./data/archive")),
                "quarantine": p(quarantine, cfg.get("quarantine_dir",
                                                    "./data/quarantine"))}

    # ------------------------------------------------------------------ #
    def _set(self, state: str, **kw):
        self.state = state
        if self.repo and self.run_id:
            self.repo.update_run(self.run_id, current_state=state)
        self.obs.on_state(state, **kw)
        self.obs.heartbeat()

    def _log(self, level, msg, code=""):
        self.obs.on_log(level, msg, code)
        if self.repo and self.run_id:
            try:
                self.repo.add_log({"job_run_id": self.run_id, "level": level,
                                   "module": "execute", "code": code,
                                   "message": msg})
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)

    def _add_step(self, state, action, target, result, page_id):
        self._seq += 1
        if self.repo and self.run_id:
            self.repo.add_step(self.run_id, self._seq, state, action,
                               target, result, 0, page_id)
        self.obs.on_step(self._seq, state, action, target, result)

    def _finalize_fail(self, state: str, e: HisBotError):
        try:
            self.op.release_all()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
        self.state = state
        if self.repo and self.run_id:
            try:
                self.repo.finish_run(self.run_id,
                                     "aborted" if state ==
                                     State.ABORTED.value else "failed",
                                     state, error_code=getattr(
                                         e, "code", "SYS-000"))
                self.repo.audit("system", "job_run_fail",
                                object_type="job_run",
                                object_id=self.run_id,
                                detail=f"{state}:{getattr(e,'code','')}:"
                                       f"{e}")
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
        self.obs.on_log("ERROR", str(e), getattr(e, "code", ""))
