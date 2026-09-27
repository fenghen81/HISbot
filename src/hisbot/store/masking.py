"""脱敏规则（文档 4.8.2 / 5.4）。

姓名保留姓氏（张*）、身份证保留前 6 后 4、手机号保留前 3 后 4、
住院号/门诊号保留后 4 位。脱敏列明文存储供展示与统计，原始值仅存密文。
"""
from __future__ import annotations


def mask_name(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return s
    if len(s) == 1:
        return "*"
    return s[0] + "*" * (len(s) - 1)


def mask_id_card(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if len(s) <= 10:
        return "*" * len(s)
    return s[:6] + "*" * (len(s) - 10) + s[-4:]


def mask_phone(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if len(s) < 7:
        return "*" * len(s)
    return s[:3] + "*" * (len(s) - 7) + s[-4:]


def mask_last4(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if len(s) <= 4:
        return "*" * len(s)
    return "*" * (len(s) - 4) + s[-4:]


MASK_RULES = {
    "name": mask_name,
    "id_card": mask_id_card,
    "idcard": mask_id_card,
    "phone": mask_phone,
    "mobile": mask_phone,
    "last4": mask_last4,
    "inpatient_no": mask_last4,
}


def mask_value(value, rule: str | None):
    if not rule:
        return value
    fn = MASK_RULES.get(rule.lower())
    return fn(value) if fn else value
