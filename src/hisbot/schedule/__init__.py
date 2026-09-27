"""定时调度（文档 4.6 / F-08）。

基于 APScheduler：按作业 cron 自动触发；同一时刻只有一个作业在执行
（一套键鼠无法并行）；受工作时间窗约束；错过触发自动合并，不补跑堆积；
执行失败不在调度层自动重试（重试由执行引擎按表 14 负责）。
"""
from .scheduler import JobScheduler, ScheduledRun

__all__ = ["JobScheduler", "ScheduledRun"]
