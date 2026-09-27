"""解析引擎（文档 4.7）：解析器路由 + 字段映射 + 质量报告。

单文件失败行比例超过阈值（默认 5%）整体判失败（PRS-003），由上层移入
quarantine，避免脏数据入库。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .mapper import FieldMapper, MappedResult
from .readers import read_file


@dataclass
class ParseResult:
    file_path: str
    ext: str
    success: bool
    parser: str = ""
    encoding: str = ""
    headers: list[str] = field(default_factory=list)
    header_row_count: int = 1
    column_count: int = 0
    total: int = 0
    ok: int = 0
    fail: int = 0
    fail_ratio: float = 0.0
    mapped: MappedResult | None = None
    detail: str = ""
    confidence: float = 1.0
    fatal_message: str = ""

    def to_report_dict(self) -> dict:
        return {
            "parser": self.parser, "header_row": self.header_row_count,
            "column_count": self.column_count, "total_rows": self.total,
            "ok_rows": self.ok, "fail_rows": self.fail,
            "fail_detail": self.detail, "confidence": self.confidence}


class FileParser:
    def __init__(self, fail_ratio_threshold: float = 0.05,
                 encoding: str = "auto"):
        self.threshold = fail_ratio_threshold
        self.encoding = encoding

    def parse(self, path: str, mapping_cfg: dict,
              derived: dict | None = None) -> ParseResult:
        ext = os.path.splitext(path)[1].lower()
        try:
            raw = read_file(path, ext, self.encoding)
        except Exception as e:
            return ParseResult(path, ext, False, fatal_message=str(e))

        mapper = FieldMapper(mapping_cfg)
        res = mapper.map_table(raw, derived)
        total = res.total
        fail = res.fail_count
        ratio = (fail / total) if total else 0.0
        ok = total - fail

        # 失败原因明细（保留前 50 条，防膨胀）
        details = [{"row_no": e.row_no, "reasons": e.reasons}
                   for e in res.errors[:50]]
        detail = json.dumps(details, ensure_ascii=False)

        # 0 行数据视为失败（空文件/表头探测异常）
        success = total > 0 and ratio <= self.threshold
        fatal = "" if success else (
            f"解析失败率 {ratio:.1%} 超过阈值 {self.threshold:.0%}"
            if total > 0 else "未解析到任何数据行")

        return ParseResult(
            file_path=path, ext=ext, success=success,
            parser=raw.parser, encoding=raw.extras.get("encoding", ""),
            headers=raw.headers, header_row_count=raw.header_row_count,
            column_count=len(raw.headers), total=total, ok=ok, fail=fail,
            fail_ratio=ratio, mapped=res, detail=detail,
            confidence=raw.confidence, fatal_message=fatal)
