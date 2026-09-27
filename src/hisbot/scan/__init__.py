"""扫描引擎（文档 3.3 M2 / 4.2）：只读探索 HIS 界面，产出导航图。

三阶段安全基线的第一阶段，不触发任何写操作；导航图是审核与执行的唯一依据。
"""
from .classifier import ElementClassifier, Category  # noqa
from .graph_store import save_graph, load_graph, encode_fp, decode_fp  # noqa
from .engine import ScanEngine, ScanObserver, ScanResult  # noqa
