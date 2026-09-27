"""OCR 引擎抽象与实现（文档技术选型 / R-06）。

优先 RapidOCR（离线 ONNX，中文识别率高）；模型不可用时降级为
NullOcrEngine（"仅模板匹配 + 人工标注"模式，F-03/F-07 仍可满足）。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.types import Rect
from .textutil import match_keyword


@dataclass
class OcrWord:
    box: Rect
    text: str
    score: float


class OcrEngine:
    name = "base"

    def recognize(self, bgr, region: Rect | None = None) -> list[OcrWord]:
        raise NotImplementedError

    def available(self) -> bool:
        return False

    def find_text(self, bgr, keywords: list[str], *,
                  region: Rect | None = None,
                  min_score: float = 0.75) -> tuple[OcrWord, str, float] | None:
        """在画面中搜索关键词，返回最佳 (词, 命中关键词, 分数)。"""
        best: tuple[OcrWord, str, float] | None = None
        for w in self.recognize(bgr, region=region):
            if w.score < min_score:
                continue
            hit, kw, sc = match_keyword(w.text, keywords, 0.85)
            if hit and (best is None or sc > best[2]):
                best = (w, kw, sc)
        return best


class RapidOcrEngine(OcrEngine):
    name = "rapidocr-onnxruntime"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self._ocr = RapidOCR()

    def available(self) -> bool:
        return True

    def recognize(self, bgr, region: Rect | None = None) -> list[OcrWord]:
        ox = oy = 0
        img = bgr
        if region is not None:
            ox, oy = region.x, region.y
            img = bgr[region.y:region.y2, region.x:region.x2]
        try:
            result, _ = self._ocr(img)
        except Exception:
            return []
        words: list[OcrWord] = []
        if not result:
            return words
        for item in result:
            try:
                box, text, score = item[0], item[1], float(item[2])
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                words.append(OcrWord(
                    Rect(int(min(xs)) + ox, int(min(ys)) + oy,
                         int(max(xs) - min(xs)), int(max(ys) - min(ys))),
                    str(text), score))
            except Exception:
                continue
        return words


class NullOcrEngine(OcrEngine):
    """降级模式：无 OCR，仅模板匹配 + 人工标注。"""
    name = "none(template+manual)"

    def available(self) -> bool:
        return False

    def recognize(self, bgr, region: Rect | None = None) -> list[OcrWord]:
        return []


_INSTANCE: OcrEngine | None = None


def try_build_ocr(*, force: bool = False) -> OcrEngine:
    """构建 OCR 引擎；任何失败都安全降级（不在构造期抛错）。"""
    global _INSTANCE
    if _INSTANCE is not None and not force:
        return _INSTANCE
    try:
        eng = RapidOcrEngine()
        _INSTANCE = eng
    except Exception:
        _INSTANCE = NullOcrEngine()
    return _INSTANCE
