"""作业配置签发与防篡改签名（文档 2.3.4 / 4.10）。

签发时 config_version +1，写入审核人、审核时间与 config_hash(SHA-256)；
执行引擎启动时重算指纹比对，任一改动（路径、目标、审核人、版本……）
都会导致指纹变化而被拒绝执行（EXE-002）。
"""
from __future__ import annotations

import copy
import json

from ..core.errors import ConfigSignatureError
from ..core.hashing import sha256_bytes
from ..core.util import now_iso

HASH_PREFIX = "sha256:"
HASH_FIELD = "config_hash"
# 纳入指纹但哈希计算时排除的字段
_EXCLUDE = {HASH_FIELD}


def _job_root(cfg: dict) -> dict:
    """取作业配置根（兼容 {'job': {...}} 与直接传 job dict）。"""
    return cfg.get("job", cfg) if isinstance(cfg, dict) else cfg


def canonical_fingerprint(cfg: dict) -> str:
    """对除 config_hash 外的全部作业字段做规范化 SHA-256。"""
    job = _job_root(cfg)
    payload = {k: v for k, v in job.items() if k not in _EXCLUDE}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return sha256_bytes(canonical.encode("utf-8"))


def sign_job(cfg: dict, reviewer: str, *, status: str = "reviewed",
             bump_version: bool = True) -> dict:
    """原地签发作业配置，返回同一 dict。"""
    job = _job_root(cfg)
    if bump_version:
        job["config_version"] = int(job.get("config_version", 0)) + 1
    job["reviewed_by"] = reviewer
    job["reviewed_at"] = now_iso()
    job["status"] = status
    digest = canonical_fingerprint(cfg)
    job[HASH_FIELD] = HASH_PREFIX + digest
    return cfg


def is_signed(cfg: dict) -> bool:
    job = _job_root(cfg)
    return bool(job.get(HASH_FIELD)) and job.get("status") in (
        "reviewed", "enabled")


def verify_job(cfg: dict, *, raise_on_fail: bool = True) -> bool:
    """校验作业配置签名。返回 True/False，失败可抛 EXE-002。"""
    job = _job_root(cfg)
    stored = job.get(HASH_FIELD, "")
    if not stored:
        if raise_on_fail:
            raise ConfigSignatureError("作业配置未审核签发")
        return False
    expect = HASH_PREFIX + canonical_fingerprint(cfg)
    # 恒定时间比较，规避时序侧信道
    import hmac as _hmac
    ok = _hmac.compare_digest(stored, expect)
    if not ok and raise_on_fail:
        raise ConfigSignatureError("作业配置签名校验失败，疑似被篡改")
    return ok


def unsigned_clone(cfg: dict) -> dict:
    """返回去掉签名的草稿副本（用于编辑后重新签发）。"""
    clone = copy.deepcopy(cfg)
    job = _job_root(clone)
    job[HASH_FIELD] = ""
    job["status"] = "draft"
    return clone
