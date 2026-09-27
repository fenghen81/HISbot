"""审核与签发（文档 3.3 M3 / 4.4，三阶段安全基线第二阶段）。

人工复核导航图：批准导航路径、标注导出目标、知悉危险点；
通过后对作业配置做 SHA-256 防篡改签发，执行前强制校验。
"""
from .service import ReviewService, ReviewError  # noqa
