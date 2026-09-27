"""失败重试策略（文档表 14）。

按异常类型给出重试次数、指数退避与重试前动作；未登记 / 致命错误
默认不重试（安全收敛），避免对危险或不可恢复故障盲目重试。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryDecision:
    retry: bool
    attempt: int
    max_retries: int
    backoff_s: float
    pre_action: str
    category: str


_RULES: dict[str, tuple[str, int, list[float], str]] = {
    # 错误码前缀/码: (类别, 最大重试, 退避序列, 重试前动作)
    "DET-001": ("locate", 3, [1, 2, 4], "重新截图，必要时滚动到元素可见区"),
    "EXE-003": ("locate", 3, [1, 2, 4], "重新截图，必要时滚动到元素可见区"),
    "DET-002": ("page", 3, [2, 4, 8], "刷新页面并重走当前路径段"),
    "EXE-004": ("page", 3, [2, 4, 8], "刷新页面并重走当前路径段"),
    "LOG-002": ("session", 5, [0, 0, 0, 0, 0], "重新登录并从当前节点继续"),
    "LOG-001": ("login", 2, [2, 4], "核对账号口令后重试，避免触发账号锁定"),
    "DLD-001": ("download", 2, [5, 10],
                "检查下载目录权限与磁盘空间，重新点击导出"),
    "DLD-002": ("download", 2, [5, 10], "重新点击导出并等待界面完成提示"),
    "DLD-003": ("download", 2, [5, 10], "重新点击导出，等待文件稳定"),
    "DBS-001": ("db", 3, [1, 2, 4], "回滚当前批次，检查磁盘与锁"),
    "DBS-002": ("db", 3, [1, 2, 4], "回滚当前批次，检查磁盘与锁"),
}

# 显式不可重试（致命 / 数据问题 / 安全 / 人工介入）
_NO_RETRY = {
    "EXE-001", "EXE-002", "SCA-001", "SCA-002",
    "DLD-004", "DLD-006", "DLD-007",
    "PRS-001", "PRS-002", "PRS-003", "PRS-004", "PRS-005",
    "DBS-003", "DBS-004", "SYS-001", "SYS-002", "SYS-003",
    "AUT-003",
}


class RetryPolicy:
    def __init__(self, rules: dict | None = None,
                 no_retry: set | None = None):
        self.rules = rules or _RULES
        self.no_retry = no_retry if no_retry is not None else _NO_RETRY

    def decide(self, code: str, attempt: int) -> RetryDecision:
        rule = self.rules.get(code)
        if rule and attempt < rule[1]:
            cat, mx, backs, action = rule
            backoff = backs[min(attempt, len(backs) - 1)]
            return RetryDecision(True, attempt, mx, backoff, action, cat)
        return RetryDecision(False, attempt,
                             rule[1] if rule else 0, 0.0,
                             "不重试，转人工/失败",
                             rule[0] if rule else "unknown")

    def is_no_retry(self, code: str) -> bool:
        return code in self.no_retry
