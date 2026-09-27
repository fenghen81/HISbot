"""模板图像匹配与模板库管理（文档 4.2.2 L2 / 4.2.3）。

多尺度归一化互相关（TM_CCOEFF_NORMED）；模板按"站点/页面/元素"三级目录
组织，文件名取元素感知哈希前 8 位，记录采集时缩放比与窗口尺寸。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..core.hashing import phash_hex
from ..core.util import ensure_dir, now_iso
from .preprocess import to_gray


@dataclass
class TemplateImage:
    template_id: str
    name: str
    image: np.ndarray
    scale_ratio: float
    ref_width: int
    ref_height: int
    site_id: str
    page_id: str
    state: str
    path: str


@dataclass
class MatchResult:
    rect: tuple[int, int, int, int]
    score: float
    scale: float
    template_id: str
    name: str

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.rect
        return x + w // 2, y + h // 2


class TemplateMatcher:
    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold

    @staticmethod
    def _prepare(img):
        return to_gray(img)

    def match(self, frame_bgr, template: TemplateImage,
              scales: list[float] | None = None) -> MatchResult | None:
        """在帧中匹配单个模板，取最高得分（多尺度）。"""
        scene = self._prepare(frame_bgr)
        tpl0 = self._prepare(template.image)
        th0, tw0 = tpl0.shape[:2]
        if scales is None:
            scales = [1.0 / max(template.scale_ratio, 0.1), 0.9, 1.0, 1.1]
        scales = sorted(set(round(s, 3) for s in scales if s > 0))
        best: MatchResult | None = None
        H, W = scene.shape[:2]
        for s in scales:
            tw, th = int(tw0 * s), int(th0 * s)
            if tw < 8 or th < 8 or tw > W or th > H:
                continue
            tpl = cv2.resize(tpl0, (tw, th), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(scene, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= self.threshold and (best is None
                                              or max_val > best.score):
                best = MatchResult((max_loc[0], max_loc[1], tw, th),
                                   float(max_val), s,
                                   template.template_id, template.name)
        return best

    def match_any(self, frame_bgr, templates: list[TemplateImage],
                  threshold: float | None = None
                  ) -> MatchResult | None:
        old = self.threshold
        if threshold is not None:
            self.threshold = threshold
        try:
            best = None
            for t in templates:
                r = self.match(frame_bgr, t)
                if r and (best is None or r.score > best.score):
                    best = r
            return best
        finally:
            self.threshold = old


class TemplateLibrary:
    def __init__(self, root: str | Path):
        self.root = ensure_dir(root)
        self.index_path = self.root / "library.json"
        self._index = self._load_index()

    def _load_index(self) -> dict:
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text("utf-8"))
            except Exception:
                return {}
        return {"templates": {}}

    def _save_index(self):
        self.index_path.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2), "utf-8")

    def save(self, site_id: str, page_id: str, name: str, img_bgr: np.ndarray,
             scale_ratio: float = 1.0, ref_size: tuple[int, int] = (0, 0),
             state: str = "normal") -> TemplateImage:
        fp = phash_hex(to_gray(img_bgr))[:8]
        tid = uuid.uuid4().hex[:10]
        d = ensure_dir(self.root / site_id / page_id)
        fname = f"{fp}_{state}_{tid}.png"
        path = d / fname
        cv2.imwrite(str(path), img_bgr)
        rh, rw = img_bgr.shape[:2]
        meta = {"template_id": tid, "name": name, "site_id": site_id,
                "page_id": page_id, "state": state, "scale_ratio": scale_ratio,
                "ref_width": ref_size[0] or rw,
                "ref_height": ref_size[1] or rh, "file": str(path),
                "hit_count": 0, "miss_count": 0,
                "status": "active", "created_at": now_iso()}
        self._index["templates"][tid] = meta
        self._save_index()
        return self._to_image(meta, img_bgr)

    def _to_image(self, meta: dict, img=None) -> TemplateImage:
        if img is None:
            img = cv2.imread(meta["file"])
        return TemplateImage(
            meta["template_id"], meta["name"], img,
            float(meta.get("scale_ratio", 1.0)),
            int(meta.get("ref_width", 0)), int(meta.get("ref_height", 0)),
            meta["site_id"], meta["page_id"], meta.get("state", "normal"),
            meta["file"])

    def load(self, site_id: str | None = None,
             page_id: str | None = None,
             name: str | None = None) -> list[TemplateImage]:
        out = []
        for _tid, m in self._index["templates"].items():
            if m.get("status") != "active":
                continue
            if site_id and m.get("site_id") != site_id:
                continue
            if page_id and m.get("page_id") != page_id:
                continue
            if name and m.get("name") != name:
                continue
            img = cv2.imread(m["file"])
            if img is not None:
                out.append(self._to_image(m, img))
        return out

    def record(self, tid: str, hit: bool):
        m = self._index["templates"].get(tid)
        if not m:
            return
        m["hit_count" if hit else "miss_count"] = \
            int(m.get("hit_count" if hit else "miss_count", 0)) + 1
        self._save_index()

    def low_hit_rate(self, threshold: float = 0.8) -> list[dict]:
        """命中率低于阈值的模板（待更新清单，文档 4.2.3）。"""
        bad = []
        for m in self._index["templates"].values():
            total = int(m.get("hit_count", 0)) + int(m.get("miss_count", 0))
            if total == 0:
                continue
            if m["hit_count"] / total < threshold:
                bad.append(m)
        return bad
