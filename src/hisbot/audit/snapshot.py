"""现场快照（文档 F-16）：失败 / 急停时保存当前屏幕、状态与日志上下文。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import json
import os
from datetime import datetime

import numpy as np

from ..core.util import now_iso


def save_snapshot(diag_dir: str, *, frame=None, state: str = "",
                  extra: dict | None = None, log_tail: list | None = None,
                  prefix: str = "snap") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    folder = os.path.join(diag_dir, f"{prefix}_{ts}")
    os.makedirs(folder, exist_ok=True)
    if frame is not None and isinstance(frame, np.ndarray):
        try:
            import cv2
            cv2.imwrite(os.path.join(folder, "screen.png"), frame)
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
    meta = {"ts": now_iso(), "state": state, "extra": extra or {},
            "log_tail": log_tail or []}
    with open(os.path.join(folder, "meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
    return folder
