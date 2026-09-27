"""下载完成界面信号 A 检测（文档 4.6.1）。

定时截取浏览器下载栏区域 / 全屏，OCR 命中完成关键词集合；
连续 N 帧（默认 2）命中才判定 A 成立，避免闪烁误判。
提示框内的"打开/在文件夹中显示"等按钮同时用于识别完成，但列入点击黑名单。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..core.types import Rect
from .ocr import OcrEngine
from .textutil import normalize_text


class DownloadSignalDetector:
    def __init__(self, ocr: OcrEngine | None,
                 keywords: list[str], hit_frames: int = 2,
                 bottom_ratio: float = 0.30,
                 min_confidence: float = 0.7,
                 fullscreen_fallback: bool = False):
        self.ocr = ocr
        self.keywords = [normalize_text(k) for k in keywords if k]
        self.hit_frames = hit_frames
        self.bottom_ratio = bottom_ratio
        self.min_confidence = min_confidence
        # 默认只扫底部下载条带（Chrome 下载栏 / 右下角 Toast 均在底部）；
        # 全屏兜底成本高，仅在明确需要时开启
        self.fullscreen_fallback = fullscreen_fallback
        self._streak = 0
        self.last_hit_word = ""

    def _scan_region(self, bgr) -> Rect:
        H, W = bgr.shape[:2]
        return Rect(0, int(H * (1 - self.bottom_ratio)), W,
                    int(H * self.bottom_ratio))

    def frame_has_prompt(self, bgr: np.ndarray) -> tuple[bool, str]:
        """单帧是否出现完成提示。先扫底部下载条带，可选全屏兜底。"""
        regions: list[Any] = [self._scan_region(bgr)]
        if self.fullscreen_fallback:
            regions.append(None)
        for region in regions:
            words = self.ocr.recognize(bgr, region=region) if self.ocr else []
            for w in words:
                if w.score < self.min_confidence:
                    continue
                nt = normalize_text(w.text)
                for kw in self.keywords:
                    if kw and (kw == nt or kw in nt):
                        return True, w.text
        return False, ""

    def record(self, bgr: np.ndarray) -> bool:
        """输入一帧，返回是否已连续 hit_frames 帧命中（信号 A 成立）。"""
        hit, word = self.frame_has_prompt(bgr)
        if hit:
            self._streak += 1
            self.last_hit_word = word
        else:
            self._streak = 0
        return self._streak >= self.hit_frames

    def reset(self):
        self._streak = 0
        self.last_hit_word = ""
