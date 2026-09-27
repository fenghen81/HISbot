"""pytest 全局配置：注册 marker、确保 src 在路径中。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: 需要 OCR/显示的端到端慢测试（默认仍执行，"
                   "可用 -m 'not integration' 跳过）")
