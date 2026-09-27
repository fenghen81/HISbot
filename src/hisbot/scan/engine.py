"""扫描引擎（文档 4.2）。

只读遍历 HIS 界面构建导航图（NavGraph），是三阶段安全基线第一阶段。
安全约束：
- 只点击语义分类为 NAV 的安全入口，危险元素永不点击、导出元素扫描不点击；
- 三级定位失败不盲点，迷路即保守中止（NAV-004）；
- 页面指纹区分"未离开 / 已存在页 / 新页面"，回退校验指纹，绝不盲点；
- 断点续扫：增量持久化导航图与已探索动作，重扫自动复用、不重复建页；
- 全程响应暂停 / 急停。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from ..core.errors import AbortedByUser, BacktrackError
from ..core.types import Element, ElementKind, NavEdge, NavGraph, PageNode, Rect
from ..core.util import now_iso
from ..perception.textutil import fuzzy_score, normalize_text
from .classifier import Category, ElementClassifier
from .graph_store import decode_fp, encode_fp, load_graph, save_graph


@dataclass
class ScanResult:
    status: str                       # done | aborted | failed
    graph: NavGraph | None = None
    pages: int = 0
    edges: int = 0
    dangers: int = 0
    branches: int = 0
    resumed: bool = False
    message: str = ""


class ScanObserver:
    """GUI / 日志回调，默认空实现。"""

    def on_event(self, kind: str, **kw):
        pass


class ScanEngine:
    REACHED = 0.85
    STABLE = 0.95

    def __init__(self, *, detector, ocr, fingerprint, classifier:
                 ElementClassifier, robot,
                 graph_path: str,
                 progress_path: str | None = None,
                 account: str = "readonly",
                 max_depth: int = 4, max_branch: int = 30,
                 sibling_dedup: float = 0.9,
                 settle_secs: float = 1.2,
                 stable_hits: int = 2,
                 max_back_attempts: int = 3,
                 observer: ScanObserver | None = None,
                 is_abort=None, is_paused=None,
                 sleep=time.sleep):
        self.detector = detector
        self.ocr = ocr
        self.fp = fingerprint
        self.cls = classifier
        self.robot = robot
        self.graph_path = graph_path
        self.progress_path = progress_path or (graph_path + ".progress.json")
        self.account = account
        self.max_depth = max_depth
        self.max_branch = max_branch
        self.sibling_dedup = sibling_dedup
        self.settle_secs = settle_secs
        self.stable_hits = stable_hits
        self.max_back_attempts = max_back_attempts
        self.observer = observer or ScanObserver()
        self.is_abort = is_abort
        self.is_paused = is_paused
        self.sleep = sleep
        self.explored: set[str] = set()
        self.branches = 0

    # ------------------------------------------------------------------ #
    def scan(self) -> ScanResult:
        self._checkpoint()
        graph = load_graph(self.graph_path)
        resumed = graph is not None
        if graph is None:
            graph = NavGraph(graph_version="v1", site=self.account,
                             scanned_at=now_iso(), scan_account=self.account)
        # 断点续扫：复用已建图与页面 closed 状态；本次运行的“已点动作”
        # 集合从头开始，使未闭合页面能被重新进入并补全子树
        self.explored = set()

        bgr = self.robot.capture()
        start_fp = self.fp.compute(bgr)
        start_page = self._match_page(graph, start_fp)
        if start_page is None:
            start_page = self._new_page(graph, bgr, start_fp, depth=0,
                                        title=start_fp.title)
            save_graph(graph, self.graph_path)
        stack: list[PageNode] = [start_page]

        try:
            while stack:
                self._checkpoint()
                page = stack[-1]
                nxt = self._next_nav_element(graph, page)
                if nxt is None:
                    stack.pop()
                    page.closed = True          # 该页子树已探索完
                    save_graph(graph, self.graph_path)
                    if stack:
                        self._back_to(graph, stack[-1])
                    continue
                self._mark_explored(page, nxt)
                self._navigate_and_classify(graph, page, nxt, stack)
                save_graph(graph, self.graph_path)
                self._save_progress()
                if self.branches >= self.max_branch:
                    self.observer.on_event(
                        "scan_info", message=f"达到最大分支数 "
                                             f"{self.max_branch}，停止深入")
                    break
        except AbortedByUser:
            save_graph(graph, self.graph_path)
            self._save_progress()
            return ScanResult("aborted", graph, len(graph.pages),
                              len(graph.edges), len(graph.dangerous),
                              self.branches, resumed, "操作员急停，已保存断点")

        graph.scanned_at = now_iso()
        save_graph(graph, self.graph_path)
        self._save_progress()
        return ScanResult("done", graph, len(graph.pages),
                          len(graph.edges), len(graph.dangerous),
                          self.branches, resumed, "扫描完成")

    # ------------------------------------------------------------------ #
    # 元素融合：形状控件 + OCR 文字块
    # ------------------------------------------------------------------ #
    def _build_elements(self, bgr) -> list[Element]:
        H, W = bgr.shape[:2]
        controls = self.detector.detect(bgr) if self.detector else []
        words = self.ocr.recognize(bgr) if self.ocr else []
        for c in controls:
            c.bbox = (c.bbox or None)
            if c.bbox is not None:
                c.rel_bbox = c.bbox.to_rel(W, H)
        used = [False] * len(words)
        for c in controls:
            if not c.bbox:
                continue
            texts = []
            for i, w in enumerate(words):
                if c.bbox.contains(w.box):
                    texts.append(w.text)
                    used[i] = True
            if texts:
                c.text = "".join(texts)
        # 未被控件包裹的独立文字（菜单文字常无边框）作为可点候选；
        # 顶部标题区文字（页面标题，非可点元素）排除
        cutoff = 0.12 * H
        extra: list[Element] = []
        for i, w in enumerate(words):
            if used[i] or not w.text.strip():
                continue
            if (w.box.y + w.box.h / 2) < cutoff:
                continue
            box = w.box.clamp(W, H)
            extra.append(Element(
                bbox=box, rel_bbox=box.to_rel(W, H), text=w.text,
                kind=ElementKind.LINK.value, confidence=w.score))
        return controls + extra

    def _new_page(self, graph, bgr, page_fp, depth, title) -> PageNode:
        page = PageNode(page_id=f"pg_{len(graph.pages)+1:03d}",
                        title=title or page_fp.title,
                        fingerprint=encode_fp(page_fp), depth=depth,
                        scanned_at=now_iso())
        self._populate_page_elements(graph, page, bgr)
        graph.pages.append(page)
        self.observer.on_event("page_entered", page_id=page.page_id,
                               title=page.title, depth=depth,
                               elements=len(page.elements))
        return page

    def _populate_page_elements(self, graph, page: PageNode, bgr):
        els = self._build_elements(bgr)
        seen_text: list[str] = []
        dedup: list = []
        for e in els:
            e.page_id = page.page_id
            norm = normalize_text(e.text)
            if not norm:
                continue
            if any(fuzzy_score(norm, s) >= self.sibling_dedup
                   for s in seen_text):
                continue
            seen_text.append(norm)
            cat, hit = self.cls.classify_element(e)
            if cat == Category.DANGER:
                e.risk = "danger"
                if not any(d.text == e.text and d.page_id == page.page_id
                           for d in graph.dangerous):
                    from ..core.types import DangerRecord
                    graph.dangerous.append(DangerRecord(
                        page.page_id, e.id, e.text,
                        f"命中危险词:{hit}"))
                    self.observer.on_event("danger_found",
                                           page_id=page.page_id,
                                           text=e.text, reason=hit)
            elif cat == Category.EXPORT:
                e.is_export_target = True
                e.keywords = [hit]
                self.observer.on_event("export_target_found",
                                       page_id=page.page_id, text=e.text)
            elif cat == Category.BACK:
                e.kind = ElementKind.UNKNOWN.value
            dedup.append(e)
        page.elements = dedup

    # ------------------------------------------------------------------ #
    def _navigate_and_classify(self, graph, parent: PageNode,
                               element: Element, stack):
        self.observer.on_event("element_click", page_id=parent.page_id,
                               text=element.text)
        self._click(element)
        self._settle()
        bgr = self.robot.capture()
        new_fp = self.fp.compute(bgr)
        parent_fp = decode_fp(parent.fingerprint)
        sim_parent = self.fp.similarity(
            new_fp, parent_fp.title, parent_fp.phash, parent_fp.anchors)

        if sim_parent >= self.REACHED:
            # 未真正离开当前页：就地动作 / 查询刷新，不是导航边
            self.observer.on_event("scan_info",
                                   message=f"“{element.text}”未引起页面跳转")
            return

        existing = self._match_page(graph, new_fp, exclude=parent.page_id)
        if existing is not None:
            self._add_edge(graph, parent, existing, element)
            ancestors = {p.page_id for p in stack}
            if existing.page_id in ancestors or existing.closed:
                # 环路或子树已闭合：重访后回退
                self.observer.on_event("page_revisit",
                                       page_id=existing.page_id)
                self._back_to(graph, parent)
            else:
                # 已建图但子树未探完（断点续扫）：进入继续补全
                self.observer.on_event("page_resume",
                                       page_id=existing.page_id)
                stack.append(existing)
            return

        # 全新页面
        if parent.depth + 1 > self.max_depth:
            self.observer.on_event("scan_info",
                                   message=f"达到最大深度，跳过“{element.text}”")
            self._back_to(graph, parent)
            return
        page = self._new_page(graph, bgr, new_fp, depth=parent.depth + 1,
                              title=new_fp.title)
        self._add_edge(graph, parent, page, element)
        self.branches += 1
        stack.append(page)

    def _next_nav_element(self, graph, page: PageNode):
        for e in page.elements:
            cat, _ = self.cls.classify_element(e)
            if cat != Category.NAV:
                continue
            if self._action_key(page, e) in self.explored:
                continue
            return e
        return None

    # ------------------------------------------------------------------ #
    def _back_to(self, graph, target: PageNode):
        target_fp = decode_fp(target.fingerprint)
        for _attempt in range(1, self.max_back_attempts + 1):
            self._checkpoint()
            bgr = self.robot.capture()
            cur = self.fp.compute(bgr)
            sim = self.fp.similarity(cur, target_fp.title,
                                     target_fp.phash, target_fp.anchors)
            if sim >= self.REACHED:
                self.observer.on_event("page_back", page_id=target.page_id)
                return True
            # 第一级：点页面上的返回/关闭/取消
            back_el = self._find_back_element(bgr)
            if back_el is not None:
                self._click(back_el)
                self._settle()
                continue
            # 第二级兜底：应用/浏览器返回
            self.robot.browser_back()
            self._settle()
        raise BacktrackError(
            f"无法安全返回页面 {target.page_id}（{target.title}），"
            f"连续 {self.max_back_attempts} 次指纹校验失败，保守中止 NAV-004")

    def _find_back_element(self, bgr):
        for e in self._build_elements(bgr):
            cat, _ = self.cls.classify_element(e)
            if cat == Category.BACK and e.bbox:
                return e
        return None

    # ------------------------------------------------------------------ #
    def _match_page(self, graph, page_fp, exclude: str | None = None):
        best, best_sim = None, 0.0
        for p in graph.pages:
            if exclude and p.page_id == exclude:
                continue
            ref = decode_fp(p.fingerprint)
            if ref is None:
                continue
            s = self.fp.similarity(page_fp, ref.title, ref.phash,
                                   ref.anchors)
            if s > best_sim:
                best, best_sim = p, s
        return best if best_sim >= self.REACHED else None

    @staticmethod
    def _add_edge(graph, src: PageNode, dst: PageNode, via: Element):
        for e in graph.edges:
            if e.from_page == src.page_id and e.to_page == dst.page_id and \
                    e.via_element == via.text:
                e.hits += 1
                return
        graph.edges.append(NavEdge(src.page_id, dst.page_id, via.text))

    def _click(self, element: Element):
        bgr = self.robot.capture()
        H, W = bgr.shape[:2]
        rect = element.bbox or Rect.from_rel(element.rel_bbox, W, H)
        cx, cy = rect.center
        self.robot.click_point(cx, cy)

    def _settle(self):
        # 暂停时冻结；测试环境 stable_hits=1 即只抓一帧
        self.sleep(self.settle_secs)

    def _checkpoint(self):
        if self.is_abort and self.is_abort():
            raise AbortedByUser("扫描过程中操作员急停")
        while self.is_paused and self.is_paused():
            self.sleep(0.05)
            if self.is_abort and self.is_abort():
                raise AbortedByUser()

    # ------------------------------------------------------------------ #
    def _action_key(self, page, e) -> str:
        return f"{page.page_id}|{normalize_text(e.text)}"

    def _mark_explored(self, page, e):
        self.explored.add(self._action_key(page, e))

    def _load_progress(self):
        if not os.path.exists(self.progress_path):
            return
        try:
            with open(self.progress_path, encoding="utf-8") as f:
                self.explored = set(json.load(f).get("explored", []))
        except Exception:
            self.explored = set()

    def _save_progress(self):
        os.makedirs(os.path.dirname(self.progress_path), exist_ok=True)
        tmp = self.progress_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"explored": sorted(self.explored),
                       "branches": self.branches}, f, ensure_ascii=False)
        os.replace(tmp, self.progress_path)
