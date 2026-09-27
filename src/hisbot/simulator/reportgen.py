"""生成符合 inpatient_daily 字段映射的仿真住院日报 xlsx。"""
from __future__ import annotations

import os

_ROWS = [
    ("D01", "内科", "I001", "床位费", "张三", "110101199001011234",
     "13800005678", "12.50"),
    ("D02", "外科", "I002", "检查费", "李四", "310101199203034567",
     "13900001111", "88.00"),
    ("D03", "儿科", "I003", "药费", "王五", "440101199512128888",
     "13712345678", "56.25"),
    ("D04", "骨科", "I004", "治疗费", "赵六", "320101198807076666",
     "13611112222", "230.00"),
]

_HEADERS = ["统计日期", "科室编码", "科室名称", "项目编码", "项目名称",
            "患者姓名", "身份证号", "联系电话", "金额(元)"]


def write_report_xlsx(path: str, report_date: str = "2026-09-22",
                      rows=None) -> str:
    import openpyxl
    rows = rows or _ROWS
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "住院日报"
    ws.append(_HEADERS)
    for r in rows:
        ws.append([report_date, *r])
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)
    return path
