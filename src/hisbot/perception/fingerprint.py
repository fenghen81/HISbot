"""页面指纹与就位判定（文档 4.2.4）。

指纹构成：标题区 OCR 文本相似度(权重 0.4) + 页面整体感知哈希(0.3)
+ 关键锚点元素集合 Jaccard(0.3)。
综合相似度 ≥0.85 判定到达；0.65~0.85 疑似（2 秒后重采样）；<0.65 未到达。
页面稳定：连续两次采样相似度 ≥0.95。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.hashing import phash_hex, phash_similarity
from .ocr import OcrEngine
from .textutil import fuzzy_score, normalize_text


@dataclass
class PageFp:
    title: str
    phash: str
    anchors: tuple[str, ...]


class PageFingerprint:
    REACHED = 0.85
    SUSPECT = 0.65
    STABLE = 0.95

    def __init__(self, ocr: OcrEngine | None = None,
                 title_ratio: float = 0.12):
        self.ocr = ocr
        self.title_ratio = title_ratio

    def compute(self, bgr: np.ndarray) -> PageFp:
        words = self.ocr.recognize(bgr) if self.ocr else []
        H = bgr.shape[0]
        title_words = [w for w in words if w.box.y2 <= self.title_ratio * H]
        title = normalize_text("".join(
            w.text for w in sorted(title_words,
                                   key=lambda w: (w.box.y, w.box.x))))
        anchors = tuple(sorted({normalize_text(w.text) for w in words
                                if normalize_text(w.text)}))
        from .preprocess import to_gray
        return PageFp(title, phash_hex(to_gray(bgr)), anchors)

    @staticmethod
    def _jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> float:
        sa, sb = set(a), set(b)
        if not sa and not sb:
            return 1.0
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def similarity(self, cur: PageFp, ref_title: str, ref_phash: str,
                   ref_anchors: tuple[str, ...]) -> float:
        title_part = fuzzy_score(cur.title, normalize_text(ref_title))
        phash_part = phash_similarity(cur.phash, ref_phash)
        anchor_part = self._jaccard(cur.anchors, ref_anchors)
        # 标题缺失时把其权重并入 phash（标题非必须）
        if not cur.title and not normalize_text(ref_title):
            # 0.4 标题权重按比例并入其余两项（3:3 -> 各 0.5）
            return 0.5 * phash_part + 0.5 * anchor_part
        return 0.4 * title_part + 0.3 * phash_part + 0.3 * anchor_part

    def verdict(self, score: float) -> str:
        if score >= self.REACHED:
            return "reached"
        if score >= self.SUSPECT:
            return "suspect"
        return "not_reached"

    @staticmethod
    def is_stable(score: float) -> bool:
        return score >= PageFingerprint.STABLE
