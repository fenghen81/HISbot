"""图像预处理（文档 4.2.1 阶段一/二）。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np


def to_gray(bgr: np.ndarray) -> np.ndarray:
    if len(bgr.shape) == 2:
        return bgr
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def adaptive_binary(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 10)


def morph_close(binary: np.ndarray, ksize: int = 3) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (ksize, ksize))
    return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)


def edges(gray: np.ndarray, lo: int = 50, hi: int = 150) -> np.ndarray:
    return cv2.Canny(gray, lo, hi, apertureSize=3)


def edge_density(edges_img: np.ndarray, rect) -> float:
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    crop = edges_img[y:y + h, x:x + w]
    if crop.size == 0:
        return 0.0
    return float((crop > 0).sum()) / crop.size


def find_rect_contours(edges_img: np.ndarray) -> Sequence[Any]:
    contours, _ = cv2.findContours(edges_img, cv2.RETR_LIST,
                                   cv2.CHAIN_APPROX_SIMPLE)
    return contours
