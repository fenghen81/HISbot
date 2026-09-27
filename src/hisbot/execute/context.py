"""运行控制标志（文档 4.5.4 / F-13）。

急停最高优先级，独立标志位；暂停冻结现场（释放键鼠、保留状态）；
单步模式下每遇到一个动作边界即阻塞，等待“单步”放行一次。
所有执行动作前调用 gate()，响应粒度 ≤50ms。
"""
from __future__ import annotations

import threading

from ..core.errors import AbortedByUser
from ..core.util import BooleanFlag


class RunControl:
    def __init__(self, sleep=None):
        self.abort_flag = BooleanFlag(False)
        self.pause_flag = BooleanFlag(False)
        self.single_step = BooleanFlag(False)
        self._step_permit = threading.Event()   # 单步放行
        self._wake = threading.Event()          # 暂停唤醒
        self._sleep = sleep or (lambda s: threading.Event().wait(s))

    # ---- 控制指令（GUI / 快捷键调用）---- #
    def emergency_stop(self):
        self.abort_flag.set()
        self.pause_flag.set(False)
        self._wake.set()        # 唤醒暂停等待；不触碰单步许可

    def request_pause(self):
        self.pause_flag.set(True)

    def resume(self):
        self.pause_flag.set(False)
        self._wake.set()

    def enable_step_mode(self):
        self.single_step.set(True)

    def disable_step_mode(self):
        self.single_step.set(False)
        self._step_permit.set()

    def step_once(self):
        """单步模式下放行一个动作。"""
        self._step_permit.set()

    @property
    def aborted(self) -> bool:
        return self.abort_flag.get()

    @property
    def paused(self) -> bool:
        return self.pause_flag.get()

    # ---- 执行动作前的统一检查点 ---- #
    def gate(self):
        if self.abort_flag.get():
            raise AbortedByUser("操作员急停")
        # 暂停优先：冻结直到继续或急停
        while self.pause_flag.get() and not self.abort_flag.get():
            self._wake.wait(0.05)
            if self.pause_flag.get():
                self._wake.clear()
        if self.abort_flag.get():
            raise AbortedByUser("操作员急停")
        # 单步：每个动作边界等待一次新的放行（先清历史许可）
        if self.single_step.get():
            self._step_permit.clear()
            while (self.single_step.get() and not self.abort_flag.get()
                   and not self.pause_flag.get()):
                if self._step_permit.wait(0.05):
                    self._step_permit.clear()
                    break
            if self.pause_flag.get():
                return self.gate()
        if self.abort_flag.get():
            raise AbortedByUser("操作员急停")
