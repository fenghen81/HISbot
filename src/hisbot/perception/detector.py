"""元素检测（文档 4.2.1）：一帧画面 -> 带置信度的可点击元素候选。

混合路线：
1) OpenCV 边缘 + 轮廓提取疑似控件矩形（有边框/背景的按钮、标签页、输入框）；
2) OCR 文字块作为锚点，向四周边缘吸附还原控件边界（无边框链接/菜单兜底）；
3) 可点击性打分（边框完整性 + 文字 + 对比度）；
4) IoU≥0.7 去重，父子包含取最小可点击单位。
危险等级（risk）默认 safe，由扫描安全模块依据黑名单标注。
"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import uuid

import cv2
import numpy as np

from ..core.hashing import phash_hex
from ..core.types import Element, ElementKind, Rect, Risk
from . import preprocess as pp
from .ocr import OcrEngine


class ElementDetector:
    def __init__(self, ocr: OcrEngine | None = None,
                 iou_threshold: float = 0.7):
        self.ocr = ocr
        self.iou_threshold = iou_threshold

    # ------------------------------------------------------------------ #
    def detect(self, bgr: np.ndarray) -> list[Element]:
        H, W = bgr.shape[:2]
        gray = pp.to_gray(bgr)
        edge = cv2.dilate(pp.edges(gray),
                          cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
                          iterations=1)
        words = self.ocr.recognize(bgr) if self.ocr else []

        candidates: list[dict] = []

        # 1) 轮廓候选（封闭四边形控件，过滤表格线/面板等噪声） ------------- #
        for cnt in pp.find_rect_contours(edge):
            x, y, w, h = cv2.boundingRect(cnt)
            r = Rect(int(x), int(y), int(w), int(h))
            if not self._shape_ok(r, W, H):
                continue
            density = pp.edge_density(edge, r)
            fill = cv2.contourArea(cnt) / max(r.area(), 1)
            if not self._is_control_quad(cnt, fill, density, r, W, H):
                continue
            candidates.append({"rect": r, "has_border": True,
                               "density": density, "words": []})

        # 2) OCR 文字锚点：归属控件框或边缘吸附外扩 ---------------------- #
        for wd in words:
            if wd.box.w <= 2 or wd.box.h <= 2:
                continue
            owner = self._smallest_containing(candidates, wd.box)
            if owner is not None:
                owner["words"].append(wd)
            else:
                rect = self._snap_to_control(wd.box, edge, W, H)
                candidates.append({"rect": rect, "has_border": False,
                                   "density": 0.0, "words": [wd]})

        # 合并同一控件的多个文字词 -> text
        merged: list[dict] = []
        for c in candidates:
            text = self._join_words(c["words"])
            c["text"] = text
            merged.append(c)

        # 3) 过滤：无文字的仅保留封闭、小尺寸、边缘适度的图标按钮 -------- #
        cleaned = [c for c in merged
                   if c["text"] or (c["has_border"]
                                    and c["density"] <= 0.4
                                    and c["rect"].w <= 0.4 * W
                                    and c["rect"].h <= 0.12 * H)]
        # 3b) 剔除成行列等距排列的同构空矩形（表格网格，非可点击控件） ---- #
        cleaned = self._drop_grid_icons(cleaned)

        # 4) 去重 + 父子归并（取最小可点击单位） ------------------------- #
        cleaned = self._dedup(cleaned)

        # 5) 生成 Element ------------------------------------------------- #
        elements: list[Element] = []
        for c in cleaned:
            r = c["rect"]
            text = c.get("text", "")
            conf = self._score(c)
            kind = self._classify(c, W, H)
            crop = gray[r.y:r.y2, r.x:r.x2]
            fp = phash_hex(crop) if crop.size else ""
            elements.append(Element(
                id=uuid.uuid4().hex[:12],
                bbox=r,
                rel_bbox=r.to_rel(W, H),
                text=text,
                kind=kind,
                confidence=round(conf, 3),
                risk=Risk.SAFE.value,
                fingerprint=fp,
                template_ids=[],
            ))
        return elements

    # ------------------------------------------------------------------ #
    @staticmethod
    def _shape_ok(r: Rect, W: int, H: int) -> bool:
        if r.w < max(24, 0.012 * W) or r.h < max(20, 0.012 * H):
            return False
        if r.w > 0.7 * W or r.h > 0.18 * H:
            return False
        aspect = r.w / max(r.h, 1)
        if aspect < 0.4 or aspect > 16:
            return False
        return True

    @staticmethod
    def _is_control_quad(cnt, fill: float, density: float, r: Rect,
                         W: int, H: int) -> bool:
        """判定轮廓是否为封闭控件四边形（排除表格线段、大面板）。"""
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.05 * peri, True)
        if len(approx) != 4:
            return False
        if fill < 0.55:
            return False
        if not (0.03 <= density <= 0.42):
            return False
        if r.w > 0.45 * W and r.h > 0.2 * H:
            return False
        return True

    @staticmethod
    def _drop_grid_icons(cands: list[dict]) -> list[dict]:
        """剔除成行列等距排列的同构无文字矩形（表格网格单元格）。"""
        from collections import defaultdict
        icons = [c for c in cands if not c.get("text")]
        if len(icons) < 3:
            return cands
        groups: dict = defaultdict(list)
        for c in icons:
            r = c["rect"]
            groups[(round(r.w / 8) * 8, round(r.h / 6) * 6)].append(c)
        drop: set[int] = set()
        for g in groups.values():
            if len(g) < 3:
                continue
            rows: dict = defaultdict(list)
            cols: dict = defaultdict(list)
            for c in g:
                rows[round(c["rect"].center[1] / 8) * 8].append(c)
                cols[round(c["rect"].center[0] / 8) * 8].append(c)

            def even_spaced(items, horizontal: bool) -> bool:
                pts = sorted(c["rect"].center[0 if horizontal else 1]
                             for c in items)
                gaps = np.diff(pts)
                return (len(gaps) >= 2 and
                        np.std(gaps) <= max(8, 0.18 * np.mean(gaps)))

            for cg in list(rows.values()) + list(cols.values()):
                if len(cg) >= 3:
                    horiz = any(len(v) >= 3 for v in rows.values()
                                if v is cg)
                    if even_spaced(cg, horiz):
                        drop.update(id(c) for c in cg)
        return [c for c in cands if id(c) not in drop]

    @staticmethod
    def _smallest_containing(candidates, box: Rect):
        best, best_area = None, None
        for c in candidates:
            r = c["rect"]
            # 文字中心落在控件内，且控件基本包住文字
            cx, cy = box.center
            if (r.x <= cx <= r.x2 and r.y <= cy <= r.y2 and
                    box.w <= r.w * 1.4 and box.h <= r.h * 1.6):
                a = r.area()
                if best_area is None or a < best_area:
                    best, best_area = c, a
        return best

    @staticmethod
    def _snap_to_control(box: Rect, edge, W: int, H: int) -> Rect:
        """以文字框为基础，在边缘图上吸附最近的水平/垂直控件边界；
        找不到则按内边距比例外扩（链接/菜单）。"""
        x, y, w, h = box.x, box.y, box.w, box.h

        def line_strength(region_slice, axis):
            return (region_slice > 0).sum(axis=axis)

        # 搜索带：上下最多 1.2 字高，左右最多 0.8 字宽
        pad_t = pad_b = int(h * 1.0)
        pad_l = pad_r = int(w * 0.35 + h * 0.4)
        x0, y0 = max(0, x - pad_l), max(0, y - pad_t)
        x1, y1 = min(W, box.x2 + pad_r), min(H, box.y2 + pad_b)
        band = edge[y0:y1, x0:x1]
        top = bottom = left = right = None
        try:
            row_sum = (band > 0).sum(axis=1)
            col_sum = (band > 0).sum(axis=0)
            # 文字框在 band 内的局部坐标
            lx, ly = x - x0, y - y0
            lx2, ly2 = box.x2 - x0, box.y2 - y0
            width_need = max(3, int(w * 0.6))
            height_need = max(3, int(h * 0.5))
            for i in range(ly - 1, -1, -1):
                if row_sum[i] >= width_need:
                    top = y0 + i
                    break
            for i in range(ly2, len(row_sum)):
                if row_sum[i] >= width_need:
                    bottom = y0 + i
                    break
            for j in range(lx - 1, -1, -1):
                if col_sum[j] >= height_need:
                    left = x0 + j
                    break
            for j in range(lx2, len(col_sum)):
                if col_sum[j] >= height_need:
                    right = x0 + j
                    break
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
        nx = left if left is not None else max(0, x - int(w * 0.25))
        ny = top if top is not None else max(0, y - int(h * 0.55))
        nx2 = right if right is not None else min(W, box.x2 + int(w * 0.25))
        ny2 = bottom if bottom is not None else min(H, box.y2 + int(h * 0.55))
        return Rect(nx, ny, max(1, nx2 - nx), max(1, ny2 - ny))

    @staticmethod
    def _join_words(words) -> str:
        words = sorted(words, key=lambda wd: (wd.box.y, wd.box.x))
        return "".join(wd.text for wd in words).strip()

    @staticmethod
    def _score(c: dict) -> float:
        s = 0.4
        if c.get("text"):
            s += 0.35
        if c.get("has_border"):
            s += 0.15
        s += min(0.1, c.get("density", 0) * 0.5)
        return min(1.0, s)

    @staticmethod
    def _classify(c: dict, W: int, H: int) -> str:
        text = c.get("text", "")
        r = c["rect"]
        if not text:
            return ElementKind.ICON.value
        pager_words = ("上一页", "下一页", "上页", "下页", "末页")
        if text in pager_words:
            return ElementKind.PAGER.value
        if text.isdigit() and r.w < 60:
            return ElementKind.PAGER.value
        if c.get("has_border"):
            return ElementKind.BUTTON.value
        # 位于窗口顶部 12% 区域的纯文字更可能是菜单/标签
        if r.y < 0.12 * H:
            return ElementKind.MENU.value
        return ElementKind.LINK.value

    def _dedup(self, cands: list[dict]) -> list[dict]:
        # 面积排序，优先保留小（更具体）的元素
        cands = sorted(cands, key=lambda c: c["rect"].area())
        kept: list[dict] = []
        for c in cands:
            r = c["rect"]
            merged_into = False
            for k in kept:
                kr = k["rect"]
                if r.iou(kr) >= self.iou_threshold:
                    # 合并：优先有边框、文字更全
                    if not k.get("has_border") and c.get("has_border"):
                        k["has_border"] = True
                    if c.get("text") and len(c["text"]) > len(
                            k.get("text", "")):
                        k["text"] = c["text"]
                    elif c.get("text") and not k.get("text"):
                        k["text"] = c["text"]
                    k["density"] = max(k.get("density", 0),
                                       c.get("density", 0))
                    merged_into = True
                    break
                # 父子包含：若当前（较小）被已存在元素显著包含，则用更小者替换
                if kr.contains(r) and kr.area() > r.area() * 1.5 and c.get(
                        "text"):
                    # 用最小可点击单位替换大框
                    k["rect"] = r
                    if c.get("text"):
                        k["text"] = c["text"]
                    k["has_border"] = c.get("has_border", k.get("has_border"))
                    merged_into = True
                    break
                if r.contains(kr) and r.area() > kr.area() * 1.5 and c.get(
                        "text"):
                    merged_into = True  # 丢弃更大的父框
                    break
            if not merged_into:
                kept.append(c)
        return kept
