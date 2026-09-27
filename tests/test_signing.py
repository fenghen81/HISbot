"""作业配置 SHA-256 签发与篡改检测测试。"""
import copy

import pytest

from hisbot.config.signing import sign_job, verify_job
from hisbot.core.errors import ConfigSignatureError


def _job():
    return {"job": {
        "job_id": "j1", "job_name": "测试", "config_version": 0,
        "path": [{"text": "报表", "approved": True}],
        "target": {"button_text": "导出"},
        "download": {"timeout_ms": 120000}}}


def test_signed_job_verifies():
    signed = sign_job(_job(), "审核员A")
    assert verify_job(signed) is True
    assert signed["job"]["status"] == "reviewed"
    assert signed["job"]["reviewed_by"] == "审核员A"
    assert signed["job"]["config_hash"]


def test_unsigned_job_rejected():
    with pytest.raises(ConfigSignatureError):
        verify_job(_job())


@pytest.mark.parametrize("mut", [
    lambda c: c["job"]["path"][0].__setitem__("text", "删除"),
    lambda c: c["job"]["target"].__setitem__("button_text", "作废"),
    lambda c: c["job"]["download"].__setitem__("timeout_ms", 1),
])
def test_tamper_detected(mut):
    signed = sign_job(_job(), "审核员A")
    tampered = copy.deepcopy(signed)
    mut(tampered)
    with pytest.raises(ConfigSignatureError):
        verify_job(tampered)
