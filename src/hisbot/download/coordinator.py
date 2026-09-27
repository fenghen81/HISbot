"""下载捕获协调器（文档 4.6，静默下载专项，全项目最高风险环节）。

完成 = 信号A(界面连续出现下载完成提示) AND 信号B(候选文件进入稳定态：
连续 N 次大小不变 + 独占打开成功 + 魔数/扩展名一致)。
任一信号缺失不得进入解析；超时按配置重试或失败，绝不解析半截文件。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..core.constants import TEMP_SUFFIXES
from ..core.errors import AbortedByUser
from .archiver import Archived, archive_file
from .magic import check_magic
from .stable import file_size, try_exclusive_open


@dataclass
class Candidate:
    path: str
    name: str
    size: int
    mtime: float
    matched_pattern: bool = False


@dataclass
class CaptureResult:
    success: bool
    archived: list[Archived] = field(default_factory=list)
    origins: list[str] = field(default_factory=list)
    signal_prompt: bool = False
    signal_stable: bool = False
    error_code: str | None = None
    message: str = ""
    elapsed_ms: int = 0

    @property
    def files(self) -> list[str]:
        return [a.path for a in self.archived]


class DownloadCoordinator:
    def __init__(self, watch_dir: str, archive_dir: str,
                 quarantine_dir: str, signal_detector,
                 *, allowed_ext=(".xlsx", ".xls", ".csv", ".pdf"),
                 temp_suffixes=TEMP_SUFFIXES,
                 sample_interval_ms: int = 500,
                 sample_count: int = 3,
                 prompt_idle_ms: int = 2000,
                 prompt_active_ms: int = 500,
                 exclusive_check: bool = True,
                 magic_check: bool = True):
        self.watch_dir = watch_dir
        self.archive_dir = archive_dir
        self.quarantine_dir = quarantine_dir
        self.signal = signal_detector
        self.allowed_ext = tuple(e.lower() for e in allowed_ext)
        self.temp_suffixes = tuple(s.lower() for s in temp_suffixes)
        self.interval = max(0.02, sample_interval_ms / 1000.0)
        self.sample_count = sample_count
        # 信号 A 两档：文件未稳定前低频兜底；文件稳定后立即快速确认提示
        self.prompt_idle = prompt_idle_ms / 1000.0
        self.prompt_active = prompt_active_ms / 1000.0
        self.exclusive_check = exclusive_check
        self.magic_check = magic_check

    # ------------------------------------------------------------------ #
    def capture(self, *, job_name: str, biz_date: str,
                started_at: float,
                expect_files: int = 1,
                name_pattern: str | None = None,
                timeout_ms: int = 120000,
                force_without_prompt: bool = False,
                get_frame: Callable | None = None,
                is_abort: Callable[[], bool] | None = None,
                is_paused: Callable[[], bool] | None = None,
                log: Callable[[str], None] | None = None,
                sleep: Callable[[float], None] = time.sleep
                ) -> CaptureResult:
        from ..core.util import ensure_dir
        ensure_dir(self.watch_dir)
        ensure_dir(self.archive_dir)
        ensure_dir(self.quarantine_dir)
        self.signal.reset()
        return self._capture_loop(
            job_name=job_name, biz_date=biz_date, started_at=started_at,
            expect_files=expect_files, name_pattern=name_pattern,
            timeout_ms=timeout_ms,
            force_without_prompt=force_without_prompt,
            get_frame=get_frame, is_abort=is_abort, is_paused=is_paused,
            log=log, sleep=sleep)

    def _capture_loop(self, *, job_name, biz_date, started_at, expect_files,
                      name_pattern, timeout_ms, force_without_prompt,
                      get_frame, is_abort, is_paused, log, sleep) -> CaptureResult:
        def _log(m):
            if log:
                log(m)

        deadline = time.time() + timeout_ms / 1000.0
        history: dict[str, list[int]] = {}
        stable: dict[str, Candidate] = {}
        quarantined: list[str] = []
        signal_A = False
        signal_B = False
        has_writing_temp = False
        t0 = time.time()
        rx = re.compile(name_pattern) if name_pattern else None
        # 文件采样与界面 OCR 为两条独立周期：采样优先，OCR 慢时其下一周期
        # 自动推后，采样到期即补，不会被慢 OCR 饿死
        next_sample = t0
        next_ocr = t0 + self.prompt_idle
        was_B = False

        while True:
            if is_abort and is_abort():
                raise AbortedByUser("下载捕获过程中操作员急停")
            while is_paused and is_paused():
                sleep(0.05)
                if is_abort and is_abort():
                    raise AbortedByUser()
                # 暂停期间冻结全部时钟
                deadline += 0.05
                next_sample += 0.05
                next_ocr += 0.05

            now = time.time()
            # 超时检查在动作之前，保证超时精确（至多过冲一次 OCR）
            if now >= deadline:
                return self._timeout_result(signal_A, signal_B, stable,
                                            quarantined, has_writing_temp,
                                            t0)

            # 信号 B：文件采样（轻量，独立周期，到期即补）--------------- #
            if now >= next_sample:
                next_sample = now + self.interval
                cands, has_writing_temp = self._scan(started_at, rx)
                for c in cands:
                    size = file_size(c.path)
                    if size <= 0:
                        continue
                    hist = history.setdefault(c.path, [])
                    hist.append(size)
                    hist[:] = hist[-self.sample_count:]
                    if len(hist) == self.sample_count and \
                            len(set(hist)) == 1 and c.path not in stable:
                        ext = os.path.splitext(c.name)[1].lower()
                        if self.magic_check and not check_magic(c.path, ext):
                            _log(f"文件头与扩展名不符，移入隔离区：{c.name}")
                            self._quarantine(c.path)
                            quarantined.append(c.name)
                            history.pop(c.path, None)
                            continue
                        if self.exclusive_check and \
                                not try_exclusive_open(c.path):
                            _log(f"文件仍被占用，继续等待：{c.name}")
                            continue
                        c.size = size
                        stable[c.path] = c
                        _log(f"文件进入稳定态：{c.name} ({size} B)")
                chosen = self._choose(stable, expect_files)
                signal_B = len(chosen) >= expect_files
                # 文件从未稳定转为稳定：立即确认界面提示（切快速档）
                if signal_B and not was_B:
                    next_ocr = now
                was_B = signal_B

            # 信号 A：界面完成提示（未稳定低频兜底，稳定后快速确认）---- #
            period = self.prompt_active if signal_B else self.prompt_idle
            if not signal_A and get_frame is not None and now >= next_ocr:
                next_ocr = now + period
                try:
                    fr = get_frame()
                    if fr is not None:
                        signal_A = self.signal.record(fr)
                except Exception:
                    signal_A = False

            # 双信号与门 ------------------------------------------------- #
            if (signal_A or force_without_prompt) and signal_B:
                archived, origins = [], []
                for c in chosen[:expect_files]:
                    info = archive_file(c.path, self.archive_dir,
                                        job_name, biz_date,
                                        os.path.splitext(c.name)[1])
                    archived.append(info)
                    origins.append(c.name)
                    _log(f"归档完成：{info.name}")
                if len(stable) > expect_files:
                    _log(f"候选文件 {len(stable)} 个多于预期 "
                         f"{expect_files}，已取最新最大 N 个（DLD-005）")
                return CaptureResult(
                    success=True, archived=archived, origins=origins,
                    signal_prompt=bool(signal_A),
                    signal_stable=True,
                    message="下载完成（双信号与门通过）",
                    elapsed_ms=int((time.time() - t0) * 1000))

            wake = next_sample
            if get_frame is not None:
                wake = min(wake, next_ocr)
            sleep(max(0.0, min(wake, deadline) - time.time()))

    # ------------------------------------------------------------------ #
    def _scan(self, started_at: float,
              rx) -> tuple[list[Candidate], bool]:
        out: list[Candidate] = []
        writing_temp = False
        try:
            names = os.listdir(self.watch_dir)
        except OSError:
            from ..core.errors import WatchDirError
            raise WatchDirError(f"下载目录不可访问：{self.watch_dir}") from None
        for name in names:
            if name.startswith("."):
                continue
            low = name.lower()
            path = os.path.join(self.watch_dir, name)
            if not os.path.isfile(path):
                continue
            if any(low.endswith(s) for s in self.temp_suffixes):
                writing_temp = True
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in self.allowed_ext:
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            # 时间窗：只接受点击导出之后新增/修改的文件
            if st.st_mtime < started_at - 1.0 and \
                    st.st_ctime < started_at - 1.0:
                continue
            matched = bool(rx.search(name)) if rx else False
            if rx and not matched:
                continue
            out.append(Candidate(path, name, st.st_size, st.st_mtime,
                                 matched))
        return out, writing_temp

    @staticmethod
    def _choose(stable: dict[str, Candidate],
                expect: int) -> list[Candidate]:
        cands = list(stable.values())
        # 命名正则命中优先；其次时间最新、体积最大
        cands.sort(key=lambda c: (c.matched_pattern, c.mtime, c.size),
                   reverse=True)
        return cands[:expect]

    def _quarantine(self, path: str):
        os.makedirs(self.quarantine_dir, exist_ok=True)
        base = os.path.basename(path)
        target = os.path.join(self.quarantine_dir, base)
        i = 1
        while os.path.exists(target):
            target = os.path.join(
                self.quarantine_dir, f"{i}_{base}")
            i += 1
        try:
            shutil.move(path, target)
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)

    def _timeout_result(self, signal_A, signal_B, stable, quarantined,
                        writing_temp, t0) -> CaptureResult:
        if quarantined:
            return CaptureResult(False, signal_prompt=signal_A,
                                 signal_stable=signal_B,
                                 error_code="DLD-004",
                                 message=f"文件魔数不符已隔离：{quarantined}",
                                 elapsed_ms=int((time.time() - t0) * 1000))
        if signal_B and not signal_A:
            return CaptureResult(False, signal_prompt=False,
                                 signal_stable=True, error_code="DLD-002",
                                 message="文件已稳定但未捕获界面完成提示",
                                 elapsed_ms=int((time.time() - t0) * 1000))
        if signal_A and not signal_B:
            return CaptureResult(False, signal_prompt=True,
                                 signal_stable=False, error_code="DLD-003",
                                 message="出现完成提示但文件未进入稳定态",
                                 elapsed_ms=int((time.time() - t0) * 1000))
        return CaptureResult(False, signal_prompt=signal_A,
                             signal_stable=signal_B,
                             error_code="DLD-001",
                             message="下载超时，未完成落盘确认"
                                     + ("（存在临时下载文件）"
                                        if writing_temp else ""),
                             elapsed_ms=int((time.time() - t0) * 1000))
