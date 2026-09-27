"""结构化操作日志与防篡改哈希链（文档 F-14 / F-15 / 附录 B）。

每条记录含 prev_hash + 自身 hash（sha256(prev_hash || canonical_json)），
仅追加写入 JSONL；任何删除、插入、篡改都会破坏后续链校验。
同时镜像到数据库 t_operation_log 供界面检索。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import hashlib
import json
import os
import threading
from collections.abc import Callable
from typing import Any

from ..core.util import now_iso

_RESERVED = {"prev_hash", "hash"}


def _canonical(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k not in _RESERVED}
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def _digest(prev: str, canon: str) -> str:
    return hashlib.sha256((prev + "\n" + canon).encode("utf-8")).hexdigest()


def _last_hash(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    last = ""
    with open(path, "rb") as f:
        try:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8", errors="ignore").splitlines()
        except Exception:
            tail = []
    for line in tail:
        try:
            last = json.loads(line).get("hash", last)
        except Exception:
            continue
    return last


class StructuredLogger:
    def __init__(self, jsonl_path: str | None = None, repo=None,
                 run_id_getter: Callable[[], str] | None = None):
        self.path = jsonl_path
        self.repo = repo
        self.run_id_getter = run_id_getter
        self._lock = threading.Lock()
        self._prev = _last_hash(jsonl_path or "")
        if jsonl_path:
            os.makedirs(os.path.dirname(os.path.abspath(jsonl_path)),
                        exist_ok=True)

    def log(self, level: str, message: str, code: str = "", **kw: Any) -> dict:
        rec = {
            "ts": now_iso(), "level": level.upper(), "code": code,
            "message": message,
            "job_run_id": (kw.pop("job_run_id", None)
                           or (self.run_id_getter() if self.run_id_getter
                               else "")),
        }
        for k in ("state", "page_id", "action", "target_desc", "coords",
                  "result", "duration_ms", "snapshot_path", "module",
                  "actor"):
            if k in kw:
                rec[k] = kw.pop(k)
        if kw:
            rec["extra"] = kw
        with self._lock:
            canon = _canonical(rec)
            rec["prev_hash"] = self._prev
            rec["hash"] = _digest(self._prev, canon)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False,
                                       default=str) + "\n")
            self._prev = rec["hash"]
        if self.repo is not None:
            try:
                self.repo.add_log({
                    "job_run_id": rec.get("job_run_id"), "ts": rec["ts"],
                    "level": rec["level"], "state": rec.get("state"),
                    "page_id": rec.get("page_id"),
                    "action": rec.get("action"),
                    "target_desc": rec.get("target_desc"),
                    "coords": (json.dumps(rec["coords"], ensure_ascii=False)
                               if isinstance(rec.get("coords"),
                                             (list, tuple, dict))
                               else rec.get("coords")),
                    "result": str(rec["result"]) if rec.get("result")
                    is not None else None,
                    "duration_ms": rec.get("duration_ms"),
                    "snapshot_path": rec.get("snapshot_path"),
                    "error_code": code})
            except Exception:
                _log.warning("忽略异常 @%s", __name__, exc_info=True)
        return rec

    def info(self, msg, code="", **kw):
        return self.log("INFO", msg, code, **kw)

    def warn(self, msg, code="", **kw):
        return self.log("WARN", msg, code, **kw)

    def error(self, msg, code="", **kw):
        return self.log("ERROR", msg, code, **kw)

    def action(self, action, target, result, **kw):
        return self.log("INFO", f"{action} {target} → {result}",
                        action=action, target_desc=target, result=result,
                        **kw)


def verify_chain(path: str) -> tuple[bool, int, str]:
    """校验哈希链。返回 (是否完整, 首个断裂行号(0表示完整), 说明)。"""
    if not os.path.isfile(path):
        return True, 0, "日志文件不存在（视为空链）"
    prev = ""
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            expect_prev = rec.get("prev_hash", "")
            if expect_prev != prev:
                return False, i, f"第{i}行前驱哈希不匹配（被插入/删除/重排）"
            canon = _canonical(rec)
            expect_hash = _digest(prev, canon)
            if rec.get("hash") != expect_hash:
                return False, i, f"第{i}行内容哈希不匹配（被篡改）"
            prev = rec["hash"]
    return True, 0, "哈希链完整"
