"""导航图持久化（断点续扫依据）。

导航图增量写入 config/graph/，中断后重扫加载已有图，跳过已访问页面，
从未完成的候选继续。指纹以 JSON 字符串内嵌于 PageNode.fingerprint。
"""
from __future__ import annotations

import json
import os

from ..core.types import NavGraph
from ..core.util import ensure_dir


def encode_fp(fp) -> str:
    return json.dumps(
        {"title": fp.title, "phash": fp.phash,
         "anchors": list(fp.anchors)}, ensure_ascii=False)


def decode_fp(s: str):
    from ..perception.fingerprint import PageFp
    if not s:
        return None
    try:
        d = json.loads(s)
        return PageFp(d.get("title", ""), d.get("phash", ""),
                      tuple(d.get("anchors", [])))
    except Exception:
        return None


def save_graph(graph: NavGraph, path: str) -> None:
    ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(graph.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # 原子替换，避免写出半截图


def load_graph(path: str) -> NavGraph | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return NavGraph.from_dict(json.load(f))
    except Exception:
        return None
