"""解析引擎与字段映射测试：xlsx/csv、清洗标准化、数据最小化、坏行阈值。"""
import os

import pytest

from hisbot.config.settings import load_yaml
from hisbot.parse import FileParser
from hisbot.parse.mapper import FieldMapper
from hisbot.parse.readers import RawTable
from hisbot.simulator.reportgen import write_report_xlsx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPING = os.path.join(ROOT, "config", "mappings", "inpatient_daily.yaml")


def test_parse_xlsx_full(tmp_path):
    p = write_report_xlsx(str(tmp_path / "r.xlsx"), "2026-09-22")
    cfg = load_yaml(MAPPING)
    pr = FileParser().parse(p, cfg, derived={"file_id": "f1"})
    assert pr.success
    assert pr.total == 4 and pr.fail == 0
    r0 = pr.mapped.rows[0]
    assert r0["report_date"] == "2026-09-22"
    assert r0["dept_code"] == "D01"
    assert r0["amount"] == 12.5
    assert r0["patient_name"] == "张三"
    assert r0["id_card"] == "110101199001011234"


def test_parse_csv_gbk(tmp_path):
    import csv
    p = str(tmp_path / "r.csv")
    with open(p, "w", encoding="gbk", newline="") as f:
        w = csv.writer(f)
        w.writerow(["统计日期", "科室编码", "项目编码", "金额(元)"])
        w.writerow(["2026/9/2", "d09", "I100", "￥66.00元"])
    pr = FileParser().parse(p, load_yaml(MAPPING))
    assert pr.success
    row = pr.mapped.rows[0]
    assert row["report_date"] == "2026-09-02"
    assert row["dept_code"] == "D09"
    assert row["amount"] == 66.0


def test_data_minimization_drops_unmapped_sensitive():
    cfg = load_yaml(MAPPING)
    mapper = FieldMapper(cfg)
    raw = RawTable(
        headers=["统计日期", "科室编码", "项目编码", "患者姓名",
                 "家庭住址", "操作员备注"],
        rows=[["2026-09-22", "D01", "I001", "张三", "某路1号", "VIP"]])
    res = mapper.map_table(raw, {"file_id": "fx"})
    assert res.fail_count == 0
    row = res.rows[0]
    assert row["patient_name"] == "张三"
    assert "家庭住址" not in str(row) and "某路1号" not in str(row)
    # 非敏感未映射列进入 ext_data
    assert "VIP" in row["ext_data"]


def test_bad_rows_over_threshold_fails(tmp_path):
    import openpyxl
    p = str(tmp_path / "bad.xlsx")
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["统计日期", "科室编码", "科室名称", "项目编码", "项目名称"])
    # 4 行中 3 行缺少必填的科室编码/项目编码 -> 坏行 75%
    ws.append(["2026-09-22", "D01", "内科", "I001", "床位费"])
    ws.append(["2026-09-22", "", "外科", "", "检查费"])
    ws.append(["2026-09-22", None, "儿科", None, "药费"])
    ws.append(["2026-09-22", "  ", "骨科", "  ", "治疗费"])
    wb.save(p)
    pr = FileParser().parse(p, load_yaml(MAPPING))
    assert pr.success is False
    assert pr.fail >= 3
