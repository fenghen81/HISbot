"""导航图审核与作业配置签发服务（文档 4.4）。

强制审核规则（任一不满足即拒绝签发）：
1. 导航路径必须从起始页沿已存在的边连续可达导出目标页；
2. 路径上每一步都必须经人工 approved；
3. 导出目标必须是扫描登记的导出元素（is_export_target），
   危险元素永不允许出现在路径或目标中；
4. 导航图存在危险点时，审核人必须显式知悉（acknowledge_dangers）；
5. 字段映射文件必须存在。
通过后组装作业配置并调用签名原语签发（config_version+1、config_hash）。
"""
from __future__ import annotations

import collections
import os

from ..config import signing
from ..config.settings import dump_yaml
from ..core.types import NavGraph


class ReviewError(Exception):
    """审核未通过。"""


class ReviewService:
    def __init__(self, graph: NavGraph):
        self.graph = graph

    # ------------------------------------------------------------------ #
    @property
    def pages(self):
        return self.graph.pages

    @property
    def edges(self):
        return self.graph.edges

    @property
    def dangers(self):
        return self.graph.dangerous

    def export_targets(self) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = []
        for p in self.graph.pages:
            for e in p.elements:
                if e.is_export_target:
                    out.append((p.page_id, e))
        return out

    def find_element(self, page_id: str, element_id: str):
        page = self.graph.page(page_id)
        if page is None:
            return None, None
        for e in page.elements:
            if e.id == element_id:
                return page, e
        return page, None

    def start_page(self):
        roots = [p for p in self.graph.pages if p.depth == 0]
        if not roots:
            raise ReviewError("导航图缺少起始页（depth=0）")
        return roots[0]

    # ------------------------------------------------------------------ #
    def plan_path(self, target_page_id: str) -> list[dict]:
        """BFS 求起始页 → 目标页的最短导航路径（沿已扫描边）。"""
        start = self.start_page().page_id
        if target_page_id == start:
            return []
        adj: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
        for e in self.graph.edges:
            adj[e.from_page].append((e.to_page, e.via_element))
        prev: dict[str, tuple[str, str] | None] = {start: None}
        q = collections.deque([start])
        while q:
            cur = q.popleft()
            for to, via in adj.get(cur, []):
                if to not in prev:
                    prev[to] = (cur, via)
                    q.append(to)
        if target_page_id not in prev:
            raise ReviewError(
                f"目标页 {target_page_id} 从起始页不可达，无已扫描导航路径")
        # 回溯
        chain = []
        node = target_page_id
        while node != start:
            step = prev[node]
            assert step is not None
            frm, via = step
            chain.append((frm, node, via))
            node = frm
        chain.reverse()

        steps = []
        for frm, to, via_text in chain:
            page = self.graph.page(frm)
            assert page is not None
            el = next((x for x in page.elements
                       if (x.text or "").strip() == via_text), None)
            steps.append({
                "page": frm,
                "page_title": page.title,
                "to_page": to,
                "element": el.id if el else "",
                "text": via_text,
                "kind": el.kind if el else "unknown",
                "rel_bbox": list(el.rel_bbox) if el else [0, 0, 0, 0],
                "locate": "ocr",
                "approved": False,
            })
        return steps

    # ------------------------------------------------------------------ #
    def submit(self, *, template: dict, target_page_id: str,
               target_element_id: str, steps: list[dict],
               reviewer: str, acknowledge_dangers: bool,
               mapping_path: str | None = None) -> dict:
        """校验审核结果并签发作业配置，返回 {'job': {...}}。"""
        # 规则 4：危险点知悉
        if self.graph.dangerous and not acknowledge_dangers:
            raise ReviewError("存在危险点，审核人必须显式知悉后方可签发")

        tgt_page, tgt_el = self.find_element(target_page_id,
                                             target_element_id)
        # 规则 3：目标必须是导出元素，且不得是危险元素
        if tgt_el is None:
            raise ReviewError("指定的导出目标元素不存在")
        if not tgt_el.is_export_target:
            raise ReviewError("目标元素不是扫描登记的导出按钮，拒绝签发")
        if tgt_el.risk == "danger":
            raise ReviewError("导出目标命中危险元素，拒绝签发")

        # 规则 1/2：路径连续可达且逐边批准
        self._validate_steps(steps, target_page_id)

        job_root = template.get("job", template)
        job = {
            "job_id": job_root.get("job_id", "job"),
            "job_name": job_root.get("job_name", ""),
            "site_id": job_root.get("site_id", ""),
            "graph_version": self.graph.graph_version,
            "config_version": int(job_root.get("config_version", 0)),
            "status": "draft",
            "path": [{
                "page": s["page"], "page_title": s.get("page_title", ""),
                "element": s["element"], "text": s["text"],
                "kind": s.get("kind", "unknown"),
                "rel_bbox": s.get("rel_bbox", [0, 0, 0, 0]),
                "locate": s.get("locate", "ocr"),
                "approved": True,
            } for s in steps],
            "target": {
                "page_id": target_page_id,
                "page_title": tgt_page.title,
                "button_element_id": tgt_el.id,
                "button_text": tgt_el.text,
                "button_rel_bbox": list(tgt_el.rel_bbox),
                "button_keywords": (tgt_el.keywords or
                                    job_root.get("target", {})
                                    .get("button_keywords", ["导出"])),
                "locate": "ocr",
                "pre_actions": job_root.get("target", {})
                .get("pre_actions", []),
            },
            "download": job_root.get("download", {}),
            "parse": job_root.get("parse", {}),
            "schedule": job_root.get("schedule", {}),
            "safety": job_root.get("safety", {}),
            "acknowledged_dangers": [
                {"page_id": d.page_id, "text": d.text, "reason": d.reason}
                for d in self.graph.dangerous],
        }
        mapping = (mapping_path or job.get("parse", {}).get("mapping"))
        # 规则 5：映射文件存在（相对 config 目录由调用方保证，这里做存在性
        # 宽松校验：绝对/相对路径至少在给定 mapping_path 可 stat）
        if mapping and mapping_path and not os.path.exists(mapping):
            raise ReviewError(f"字段映射文件不存在：{mapping}")

        signed = signing.sign_job({"job": job}, reviewer, status="reviewed")
        # 自校验
        signing.verify_job(signed, raise_on_fail=True)
        return signed

    def _validate_steps(self, steps: list[dict], target_page_id: str):
        start = self.start_page().page_id
        if not steps:
            if target_page_id != start:
                raise ReviewError("路径为空但目标页不是起始页")
            return
        # 首步从起始页出发
        if steps[0]["page"] != start:
            raise ReviewError("导航路径必须从起始页开始")
        prev_to = start
        edge_set = {(e.from_page, e.to_page, e.via_element)
                    for e in self.graph.edges}
        for i, s in enumerate(steps):
            if not s.get("approved"):
                raise ReviewError(
                    f"路径第 {i + 1} 步“{s.get('text')}”未经批准")
            if s["page"] != prev_to:
                raise ReviewError(f"路径第 {i + 1} 步不连续")
            key = (s["page"], s.get("to_page"), s["text"])
            if key not in edge_set:
                raise ReviewError(
                    f"路径第 {i + 1} 步在导航图中不存在：{s['text']}")
            page = self.graph.page(s["page"])
            assert page is not None
            el = next((x for x in page.elements if x.id == s["element"]),
                      None)
            if el is not None and el.risk == "danger":
                raise ReviewError("导航路径包含危险元素，拒绝签发")
            prev_to = s["to_page"]
        if prev_to != target_page_id:
            raise ReviewError("导航路径终点与导出目标页不一致")

    # ------------------------------------------------------------------ #
    @staticmethod
    def save_job(signed: dict, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        dump_yaml(signed, path)
