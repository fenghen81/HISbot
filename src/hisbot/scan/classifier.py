"""元素只读安全分类（文档 4.2.2 三重只读之语义拦截）。

扫描阶段对可点元素按文本语义分类，默认收敛（OTHER 不点）：
- DANGER 命中危险/写操作词：永不点击，只登记危险点；
- EXPORT 导出类：记录为目标按钮，扫描阶段不点击（执行阶段按签发配置走）；
- BACK   返回类：用于页面回退；
- NAV    安全导航/查询类：唯一允许在扫描中点击以深入的入口；
- OTHER  其它：不点击。
"""
from __future__ import annotations

import enum

from ..core.types import Risk
from ..perception.textutil import normalize_text


class Category(str, enum.Enum):
    NAV = "nav"
    DANGER = "danger"
    EXPORT = "export"
    BACK = "back"
    OTHER = "other"


class ElementClassifier:
    def __init__(self, blacklist: list[str], export_keywords: list[str],
                 back_keywords: list[str], nav_safe: list[str]):
        self.blacklist = [normalize_text(w) for w in blacklist if w]
        self.export_kw = [normalize_text(w) for w in export_keywords if w]
        self.back_kw = [normalize_text(w) for w in back_keywords if w]
        self.nav_kw = [normalize_text(w) for w in nav_safe if w]

    @staticmethod
    def _hit(text: str, words: list[str]) -> str:
        for w in words:
            if w and (w in text or text in w):
                return w
        return ""

    def classify_text(self, text: str) -> tuple[Category, str]:
        t = normalize_text(text)
        if not t:
            return Category.OTHER, ""
        # 危险写操作最高优先
        hit = self._hit(t, self.blacklist)
        if hit:
            return Category.DANGER, hit
        hit = self._hit(t, self.export_kw)
        if hit:
            return Category.EXPORT, hit
        hit = self._hit(t, self.back_kw)
        if hit:
            return Category.BACK, hit
        hit = self._hit(t, self.nav_kw)
        if hit:
            return Category.NAV, hit
        return Category.OTHER, ""

    def classify_element(self, element) -> tuple[Category, str]:
        return self.classify_text(element.text or "")

    @staticmethod
    def risk_for(category: Category) -> str:
        return Risk.DANGER.value if category == Category.DANGER \
            else Risk.SAFE.value
