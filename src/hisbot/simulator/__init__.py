"""仿真 HIS 系统：无真实 HIS 环境时用于端到端演示、训练与自动化测试。

- headless.py：离屏帧渲染 + 与真实操作员同接口的 SimHis（pytest 用）
- app.py：可独立启动的 PySide6 仿真 HIS 窗口（XTest 真机演示用）
- reportgen.py：生成符合住院日报字段映射的报表文件
"""
from .reportgen import write_report_xlsx

__all__ = ["write_report_xlsx"]
