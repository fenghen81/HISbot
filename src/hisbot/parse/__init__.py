"""数据处理层 L4 - 解析引擎（文档 3.3 M8 / 4.7）。"""
from .engine import FileParser, ParseResult  # noqa
from .mapper import FieldMapper  # noqa
from .readers import read_file, RawTable  # noqa
