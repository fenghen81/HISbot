"""执行 / 扫描工作线程：耗时操作全部移出 GUI 主线程。

RunControl 在主线程创建并暴露给控制按钮；observer 回调通过 Qt 信号
排队投递到主线程刷新镜像、日志与进度。
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QThread, Signal

from ..execute.context import RunControl


class RunThread(QThread):
    state_changed = Signal(str, str)
    log_appended = Signal(dict)
    step_changed = Signal(int, int)
    current_action = Signal(str)
    target_hint = Signal(str, tuple, str)     # 描述, 客户区矩形, 状态
    target_done = Signal(str, tuple)
    operator_ready = Signal(object)
    finished_result = Signal(object)

    def __init__(self, container, job_cfg: dict, biz_date: str,
                 sim: bool = False, sim_kwargs=None, parent=None):
        super().__init__(parent)
        self.c = container
        self.job_cfg = job_cfg
        self.biz_date = biz_date or date.today().strftime("%Y%m%d")
        self.sim = sim
        self.sim_kwargs = sim_kwargs
        self.control = RunControl(sleep=self._wait)

    @staticmethod
    def _wait(s):
        QThread.msleep(int(s * 1000))

    def run(self):
        from ..execute.engine import ExecObserver

        worker = self

        class Obs(ExecObserver):
            def on_state(self_inner, state, **kw):
                worker.state_changed.emit(state, str(kw.get("desc", "")))

            def on_log(self_inner, level, message, code=""):
                worker.log_appended.emit(
                    {"level": level, "code": code or "", "message": message})

            def on_step(self_inner, seq, state, action, target, result):
                worker.step_changed.emit(seq, 0)
                worker.log_appended.emit(
                    {"level": "INFO", "code": "", "state": state,
                     "action": action, "target": target, "result": result})

            def on_target(self_inner, text, rect, state):
                worker.target_hint.emit(text, tuple(rect), state)

            def heartbeat(self_inner):
                worker.c.watchdog.beat()

        try:
            result = self.c.run_job(
                self.job_cfg, self.biz_date, control=self.control,
                observer=Obs(), sim=self.sim, sim_kwargs=self.sim_kwargs,
                on_operator=lambda op: self.operator_ready.emit(op))
            self.finished_result.emit(result)
        except Exception as e:  # noqa: BLE001
            self.log_appended.emit(
                {"level": "ERROR", "code": "SYS-000", "message": str(e)})
            self.finished_result.emit(None)

    # ---- 主线程调用的控制（≤50ms 响应）---- #
    def pause(self):
        if self.control.paused:
            self.control.resume()
        else:
            self.control.request_pause()

    def step_once(self):
        if not self.control.single_step.get():
            self.control.enable_step_mode()
        self.control.step_once()

    def emergency_stop(self):
        self.control.emergency_stop()


class ScanThread(QThread):
    event = Signal(str, dict)
    scan_finished = Signal(object)
    operator_ready = Signal(object)

    def __init__(self, container, *, sim=True, sim_kwargs=None, parent=None):
        super().__init__(parent)
        self.c = container
        self.sim = sim
        self.sim_kwargs = sim_kwargs
        self.control = RunControl(sleep=self._wait)

    @staticmethod
    def _wait(s):
        QThread.msleep(int(s * 1000))

    def run(self):
        from ..scan.engine import ScanEngine, ScanObserver
        from ..simulator.headless import SimHis
        if self.sim:
            kw = {"watch_dir": str(self.c.center.watch_dir),
                  "start_page": "home"}
            kw.update(self.sim_kwargs or {})
            operator = SimHis(**kw)
        else:
            self.event.emit("scan_info", {"message":
                            "真实环境扫描：请确认已用只读账号登录到 HIS 首页"})
            operator = self.c.build_real_operator(self.control)
        self.operator = operator
        self.operator_ready.emit(operator)
        ocr, _loc, fp, detector, classifier = self.c.build_perception()
        scan_cfg = self.c.app.get("scan", {})
        graph_path = str(self.c.center.graph_path("v1"))

        class Obs(ScanObserver):
            def on_event(self_inner, kind, **kw):
                self.event.emit(kind, dict(kw))

        eng = ScanEngine(
            detector=detector, ocr=ocr, fingerprint=fp,
            classifier=classifier, robot=operator, graph_path=graph_path,
            account=(self.c.get_credential()[0] or "readonly"),
            max_depth=int(scan_cfg.get("max_depth", 4)),
            max_branch=int(scan_cfg.get("max_branch", 30)),
            sibling_dedup=float(scan_cfg.get("sibling_dedup_similarity",
                                             0.9)),
            observer=Obs(), is_abort=lambda: self.control.aborted,
            is_paused=lambda: self.control.paused,
            sleep=self._wait)
        result = eng.scan()
        self.scan_finished.emit(result)

    def emergency_stop(self):
        self.control.emergency_stop()
