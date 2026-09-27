"""核心领域类型与枚举。

严格对齐《HIS 离线数据采集工具 软件开发文档》第 4 章数据结构。
所有上层模块只依赖本模块的类型，不依赖具体平台实现。
"""
from __future__ import annotations

import enum
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #
class Risk(str, enum.Enum):
    """元素危险等级。"""
    SAFE = "safe"
    WARN = "warn"
    DANGER = "danger"


class ElementKind(str, enum.Enum):
    BUTTON = "button"
    LINK = "link"
    MENU = "menu"
    TAB = "tab"
    INPUT = "input"
    ICON = "icon"
    PAGER = "pager"
    UNKNOWN = "unknown"


class State(str, enum.Enum):
    """执行引擎显式状态机（文档 4.5.1）。"""
    IDLE = "IDLE"
    INIT = "INIT"
    LOGIN = "LOGIN"
    NAVIGATE = "NAVIGATE"
    TARGET = "TARGET"
    EXPORT = "EXPORT"
    DOWNLOAD = "DOWNLOAD"
    PARSE = "PARSE"
    PERSIST = "PERSIST"
    RETRY = "RETRY"
    DONE = "DONE"
    PAUSED = "PAUSED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


# 扫描阶段状态
SCAN_IDLE = "IDLE"
SCAN_SCANNING = "SCANNING"
SCAN_DONE = "SCAN_DONE"
SCAN_REVIEWING = "REVIEWING"
SCAN_READY = "READY"
SCAN_RUNNING = "RUNNING"


class LogLevel(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


# --------------------------------------------------------------------------- #
# 几何类型
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rect:
    """像素矩形（相对窗口客户区或屏幕，依上下文而定）。"""
    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def contains(self, other: Rect) -> bool:
        return (self.x <= other.x and self.y <= other.y and
                self.x2 >= other.x2 and self.y2 >= other.y2)

    def intersection(self, other: Rect) -> Rect:
        x1 = max(self.x, other.x)
        y1 = max(self.y, other.y)
        x2 = min(self.x2, other.x2)
        y2 = min(self.y2, other.y2)
        if x2 <= x1 or y2 <= y1:
            return Rect(0, 0, 0, 0)
        return Rect(x1, y1, x2 - x1, y2 - y1)

    def iou(self, other: Rect) -> float:
        """交并比，用于元素去重（阈值 0.7）。"""
        inter = self.intersection(other).area()
        union = self.area() + other.area() - inter
        return inter / union if union > 0 else 0.0

    def clamp(self, bw: int, bh: int) -> Rect:
        x = max(0, min(self.x, bw - 1))
        y = max(0, min(self.y, bh - 1))
        w = max(1, min(self.w, bw - x))
        h = max(1, min(self.h, bh - y))
        return Rect(x, y, w, h)

    def to_rel(self, bw: int, bh: int) -> tuple[float, float, float, float]:
        return (round(self.x / bw, 6), round(self.y / bh, 6),
                round(self.w / bw, 6), round(self.h / bh, 6))

    @staticmethod
    def from_rel(rel: tuple[float, float, float, float],
                 bw: int, bh: int) -> Rect:
        rx, ry, rw, rh = rel
        return Rect(int(rx * bw), int(ry * bh),
                    max(1, int(rw * bw)), max(1, int(rh * bh)))


# --------------------------------------------------------------------------- #
# 屏幕 / 窗口 / 文件系统事件
# --------------------------------------------------------------------------- #
@dataclass
class WindowInfo:
    hwid: str                 # 平台窗口句柄（字符串化）
    title: str
    x: int
    y: int
    w: int
    h: int
    pid: int = 0              # 窗口所属进程 ID（取不到为 0）


@dataclass
class Frame:
    """一帧画面。image 为 BGR np.ndarray。"""
    image: Any
    ts: float
    window_hwid: str | None = None
    width: int = 0
    height: int = 0

    def __post_init__(self):
        if self.image is not None:
            self.height, self.width = self.image.shape[:2]


class FsEventType(str, enum.Enum):
    CREATED = "created"
    MODIFIED = "modified"
    MOVED = "moved"
    DELETED = "deleted"


@dataclass
class FsEvent:
    type: FsEventType
    path: str
    ts: float = 0.0


# --------------------------------------------------------------------------- #
# 元素 / 页面 / 导航图
# --------------------------------------------------------------------------- #
@dataclass
class Element:
    """可点击元素（文档 4.2.1）。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    page_id: str = ""
    bbox: Rect | None = None
    # 0~1 归一化坐标 (x, y, w, h)，与分辨率无关
    rel_bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    text: str = ""
    kind: str = ElementKind.UNKNOWN.value
    confidence: float = 0.0
    template_ids: list[str] = field(default_factory=list)
    risk: str = Risk.SAFE.value
    fingerprint: str = ""
    # 审核阶段标注
    is_export_target: bool = False
    keywords: list[str] = field(default_factory=list)
    approved: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.bbox is not None:
            d["bbox"] = asdict(self.bbox)
        d["rel_bbox"] = list(self.rel_bbox)
        return d

    @staticmethod
    def from_dict(d: dict) -> Element:
        d = dict(d)
        bb = d.pop("bbox", None)
        rb = d.pop("rel_bbox", (0, 0, 0, 0))
        e = Element(**{k: v for k, v in d.items()
                       if k in Element.__dataclass_fields__})
        if bb:
            e.bbox = Rect(**bb)
        e.rel_bbox = tuple(rb)  # type: ignore
        return e


@dataclass
class PageNode:
    page_id: str
    title: str = ""
    fingerprint: str = ""
    anchor_url: str | None = None
    snapshot: str | None = None
    depth: int = 0
    scanned_at: str = ""
    elements: list[Element] = field(default_factory=list)
    # 子树是否已探索完毕（断点续扫据此决定重访时深入还是回退）
    closed: bool = False

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "fingerprint": self.fingerprint,
            "anchor_url": self.anchor_url,
            "snapshot": self.snapshot,
            "depth": self.depth,
            "scanned_at": self.scanned_at,
            "elements": [e.to_dict() for e in self.elements],
            "closed": self.closed,
        }

    @staticmethod
    def from_dict(d: dict) -> PageNode:
        return PageNode(
            page_id=d["page_id"],
            title=d.get("title", ""),
            fingerprint=d.get("fingerprint", ""),
            anchor_url=d.get("anchor_url"),
            snapshot=d.get("snapshot"),
            depth=d.get("depth", 0),
            scanned_at=d.get("scanned_at", ""),
            elements=[Element.from_dict(e) for e in d.get("elements", [])],
            closed=d.get("closed", False),
        )


@dataclass
class NavEdge:
    from_page: str
    to_page: str
    via_element: str
    hits: int = 1
    approved: bool = False

    def to_dict(self) -> dict:
        return {"from": self.from_page, "to": self.to_page,
                "via_element": self.via_element, "hits": self.hits,
                "approved": self.approved}

    @staticmethod
    def from_dict(d: dict) -> NavEdge:
        return NavEdge(d["from"], d["to"], d["via_element"],
                       d.get("hits", 1), d.get("approved", False))


@dataclass
class DangerRecord:
    page_id: str
    element_id: str
    text: str
    reason: str

    def to_dict(self) -> dict:
        return {"page_id": self.page_id, "element_id": self.element_id,
                "text": self.text, "reason": self.reason}


@dataclass
class NavGraph:
    """扫描阶段唯一产物 / 审核与执行唯一依据（文档 4.4）。"""
    graph_version: str
    site: str = ""
    scanned_at: str = ""
    scan_account: str = ""
    pages: list[PageNode] = field(default_factory=list)
    edges: list[NavEdge] = field(default_factory=list)
    dangerous: list[DangerRecord] = field(default_factory=list)

    def page(self, page_id: str) -> PageNode | None:
        return next((p for p in self.pages if p.page_id == page_id), None)

    def to_dict(self) -> dict:
        return {
            "graph_version": self.graph_version,
            "site": self.site,
            "scanned_at": self.scanned_at,
            "scan_account": self.scan_account,
            "pages": [p.to_dict() for p in self.pages],
            "edges": [e.to_dict() for e in self.edges],
            "dangerous": [d.to_dict() for d in self.dangerous],
        }

    @staticmethod
    def from_dict(d: dict) -> NavGraph:
        return NavGraph(
            graph_version=d["graph_version"],
            site=d.get("site", ""),
            scanned_at=d.get("scanned_at", ""),
            scan_account=d.get("scan_account", ""),
            pages=[PageNode.from_dict(p) for p in d.get("pages", [])],
            edges=[NavEdge.from_dict(e) for e in d.get("edges", [])],
            dangerous=[DangerRecord(**x) for x in d.get("dangerous", [])],
        )


# --------------------------------------------------------------------------- #
# 函数式辅助
# --------------------------------------------------------------------------- #
Handle = Any
Callback = Callable[..., None]
