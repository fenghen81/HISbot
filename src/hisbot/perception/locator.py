"""三级定位策略（文档 4.2.2）。

L1 OCR 关键词文字定位 → L2 多尺度模板图像匹配 → L3 人工标注兜底坐标。
任一命中即止；三级全部失败返回 None，由上层暂停请求人工介入，绝不盲点。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.types import Rect
from .ocr import OcrEngine
from .template import TemplateImage, TemplateMatcher


@dataclass
class Located:
    x: int
    y: int
    level: str            # ocr | template | manual
    score: float
    desc: str
    rect: Rect | None = None


class Locator:
    def __init__(self, ocr: OcrEngine | None,
                 matcher: TemplateMatcher | None = None,
                 levels: tuple[str, ...] = ("ocr", "template", "manual"),
                 ocr_min_confidence: float = 0.75):
        self.ocr = ocr
        self.matcher = matcher or TemplateMatcher()
        self.levels = levels
        self.ocr_min = ocr_min_confidence

    def locate(self, frame_bgr: np.ndarray, *,
               keywords: list[str] | None = None,
               templates: list[TemplateImage] | None = None,
               manual_rel: tuple[float, float] | None = None,
               template_threshold: float = 0.85,
               ) -> Located | None:
        H, W = frame_bgr.shape[:2]
        for level in self.levels:
            if level == "ocr" and self.ocr and keywords:
                found = self.ocr.find_text(
                    frame_bgr, keywords, min_score=self.ocr_min)
                if found:
                    wd, kw, sc = found
                    cx, cy = wd.box.center
                    return Located(cx, cy, "ocr", sc,
                                   f"OCR文字「{wd.text}」≈{kw}", wd.box)
            elif level == "template" and templates:
                r = self.matcher.match_any(frame_bgr, templates,
                                           template_threshold)
                if r:
                    cx, cy = r.center
                    return Located(cx, cy, "template", r.score,
                                   f"模板「{r.name}」({r.score:.2f})",
                                   Rect(*r.rect))
            elif level == "manual" and manual_rel:
                rx, ry = manual_rel
                x, y = int(rx * W), int(ry * H)
                return Located(x, y, "manual", 1.0,
                               f"人工标注({rx:.2f},{ry:.2f})")
        return None
