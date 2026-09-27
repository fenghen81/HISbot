"""清洗与类型转换（文档 4.7.2 清洗规则 / B.5 transforms）。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import datetime as _dt
import re
from decimal import Decimal, InvalidOperation

from ..perception.textutil import sbc2dbc


def t_strip(v):
    return str(v).strip() if v is not None else ""


def t_upper(v):
    return str(v).strip().upper()


def t_lower(v):
    return str(v).strip().lower()


def t_sbc2dbc(v):
    return sbc2dbc(str(v))


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def t_strip_unit(v):
    """数值单位剥离：'1,234 元' / '￥1,234.50' -> '1234.50'。"""
    s = str(v).strip().replace(",", "").replace("，", "")
    m = _NUM_RE.search(s)
    return m.group(0) if m else s


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d",
                 "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S")


def t_to_date(v):
    s = str(v).strip()
    if not s:
        return ""
    m = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", s)
    if m:
        y, mo, d = map(int, m.groups())
        return _dt.date(y, mo, d).isoformat()
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    # 兜底 pandas
    try:
        import pandas as pd
        ts = pd.to_datetime(s, errors="coerce")
        if not pd.isna(ts):
            return ts.date().isoformat()
    except Exception:
        _log.warning("忽略异常 @%s", __name__, exc_info=True)
    raise ValueError(f"无法解析日期：{v!r}")


def t_to_decimal(v):
    s = t_strip_unit(v)
    if s in ("", None):
        return None
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        raise ValueError(f"无法解析数值：{v!r}") from None


def t_to_int(v):
    s = t_strip_unit(v)
    if s in ("", None):
        return None
    return int(float(s))


def t_to_bool(v):
    s = str(v).strip().lower()
    if s in ("是", "true", "1", "y", "yes", "男"):
        return 1
    if s in ("否", "false", "0", "n", "no", "女"):
        return 0
    raise ValueError(f"无法解析布尔：{v!r}")


TRANSFORMS = {
    "strip": t_strip,
    "upper": t_upper,
    "lower": t_lower,
    "sbc2dbc": t_sbc2dbc,
    "strip_unit": t_strip_unit,
    "to_date": t_to_date,
    "to_decimal": t_to_decimal,
    "to_int": t_to_int,
    "to_bool": t_to_bool,
}

TYPE_COERCERS = {
    "text": lambda v: str(v).strip(),
    "str": lambda v: str(v).strip(),
    "date": t_to_date,
    "decimal": t_to_decimal,
    "number": t_to_decimal,
    "int": t_to_int,
    "integer": t_to_int,
    "bool": t_to_bool,
    "boolean": t_to_bool,
}


def apply_transforms(value, names: list[str]):
    for n in names or []:
        fn = TRANSFORMS.get(n)
        if fn:
            value = fn(value)
    return value


def coerce(value, type_name: str):
    if value is None or value == "":
        return value
    fn = TYPE_COERCERS.get((type_name or "text").lower())
    return fn(value) if fn else str(value)
