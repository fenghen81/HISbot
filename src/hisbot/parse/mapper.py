"""字段映射（文档 4.7.3 / B.5）。

源文件列 -> 目标表字段；支持 transforms 清洗、类型转换、必填/枚举校验、
常量列（default）、派生列（derived：file_id/batch_id 等）、
未映射敏感列丢弃（数据最小化）、其余未映射列进 ext_data(JSON)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..perception.textutil import normalize_text
from . import cleaner
from .readers import RawTable

# 未映射但疑似敏感的列名 -> 直接丢弃，不入库（文档 5.4 数据最小化）
SENSITIVE_HINTS = ("姓名", "身份证", "证号", "电话", "手机", "住院号",
                   "门诊号", "病历号", "银行卡", "住址", "地址")


@dataclass
class RowError:
    row_no: int
    reasons: list[str]
    raw: list[str]


@dataclass
class MappedResult:
    target_table: str
    business_key: list[str]
    rows: list[dict] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    sensitive_specs: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rows) + len(self.errors)

    @property
    def ok_count(self) -> int:
        return len(self.rows)

    @property
    def fail_count(self) -> int:
        return len(self.errors)


class FieldMapper:
    def __init__(self, mapping_cfg: dict):
        fm = mapping_cfg.get("field_mapping", mapping_cfg)
        self.target_table = fm["target_table"]
        self.business_key = list(fm.get("business_key", []))
        self.columns = list(fm.get("columns", []))
        self.on_conflict = fm.get("on_conflict", "update")
        self.drop_unmapped_sensitive = bool(
            fm.get("drop_unmapped_sensitive", True))
        self.keep_unmapped_as_ext = bool(fm.get("keep_unmapped_as_ext", True))
        self.sensitive_specs = [
            {"target": c["target"],
             "encrypt": bool(c.get("encrypt", c.get("sensitive"))),
             "mask_rule": c.get("mask_rule"),
             "index_mode": c.get("index_mode")}
            for c in self.columns if c.get("sensitive")]

    def map_table(self, raw: RawTable, derived: dict | None = None
                  ) -> MappedResult:
        derived = derived or {}
        result = MappedResult(self.target_table, self.business_key,
                              sensitive_specs=self.sensitive_specs)
        idx = {normalize_text(h): i for i, h in enumerate(raw.headers)}
        mapped_sources = {normalize_text(c["source"]) for c in self.columns
                          if c.get("source")}

        for ri, src_row in enumerate(raw.rows):
            row_no = raw.header_row_count + ri + 1
            rec: dict[str, Any] = {}
            reasons: list[str] = []
            for spec in self.columns:
                target = spec["target"]
                source = spec.get("source")
                value: Any = None
                if source:
                    key = normalize_text(source)
                    if key not in idx:
                        if spec.get("required"):
                            reasons.append(f"缺失必填列「{source}」")
                        if "default" in spec:
                            rec[target] = spec["default"]
                        continue
                    value = src_row[idx[key]] if idx[key] < len(src_row) else ""
                    try:
                        value = cleaner.apply_transforms(
                            value, spec.get("transforms", []))
                        value = cleaner.coerce(value, spec.get("type", "text"))
                    except Exception as e:
                        reasons.append(f"字段「{source}」转换失败：{e}")
                        value = None
                    if (value is None or value == "") and spec.get("required"):
                        reasons.append(f"必填列「{source}」为空")
                    if (value is None or value == "") and "default" in spec:
                        value = spec["default"]
                    enum = spec.get("enum")
                    if enum and value not in (None, "") and value not in enum:
                        reasons.append(
                            f"字段「{source}」枚举值非法：{value}")
                else:
                    # 常量 / 派生列
                    dv = spec.get("derived")
                    if dv and dv in derived:
                        value = derived[dv]
                    elif "default" in spec:
                        value = spec["default"]
                rec[target] = value

            # 业务主键校验
            for k in self.business_key:
                if rec.get(k) in (None, ""):
                    reasons.append(f"业务主键 {k} 为空")

            # 未映射列处理
            ext = self._unmapped_ext(raw.headers, src_row, mapped_sources)
            if ext:
                rec["ext_data"] = json.dumps(ext, ensure_ascii=False,
                                             default=str)

            if reasons:
                result.errors.append(RowError(row_no, reasons,
                                              list(src_row)))
            else:
                rec["source_row_no"] = row_no
                result.rows.append(rec)
        return result

    def _unmapped_ext(self, headers, src_row, mapped_sources) -> dict:
        ext: dict = {}
        for i, h in enumerate(headers):
            if normalize_text(h) in mapped_sources:
                continue
            val = src_row[i] if i < len(src_row) else ""
            if str(val).strip() == "":
                continue
            sensitive = any(hint in h for hint in SENSITIVE_HINTS)
            if sensitive and self.drop_unmapped_sensitive:
                continue  # 数据最小化：丢弃
            if self.keep_unmapped_as_ext:
                ext[h] = val
        return ext
