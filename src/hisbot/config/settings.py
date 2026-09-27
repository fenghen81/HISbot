"""YAML 配置读写与递归属性字典。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class AttrDict(dict):
    """支持属性访问的字典，自动递归包裹嵌套 dict/list。"""

    def __getattr__(self, name: str) -> Any:
        try:
            v = self[name]
        except KeyError as e:
            raise AttributeError(name) from e
        return v

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError as e:
            raise AttributeError(name) from e

    @staticmethod
    def wrap(obj: Any) -> Any:
        if isinstance(obj, dict):
            return AttrDict({k: AttrDict.wrap(v) for k, v in obj.items()})
        if isinstance(obj, list):
            return [AttrDict.wrap(v) for v in obj]
        return obj

    def to_plain(self) -> Any:
        if isinstance(self, dict):
            return {k: _to_plain(v) for k, v in self.items()}
        return _to_plain(self)


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


def load_yaml(path: str | Path) -> AttrDict:
    p = Path(path)
    if not p.exists():
        return AttrDict()
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return AttrDict.wrap(data)


def dump_yaml(obj: Any, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(_to_plain(obj), f, allow_unicode=True,
                       sort_keys=False, default_flow_style=False)
