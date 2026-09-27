"""文字归一化与模糊匹配（关键词定位、黑名单、下载完成词）。"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def sbc2dbc(s: str) -> str:
    """全角转半角（文档清洗规则之一）。"""
    out = []
    for ch in str(s):
        code = ord(ch)
        if code == 0x3000:
            code = 32
        elif 0xFF01 <= code <= 0xFF5E:
            code -= 0xFEE0
        out.append(chr(code))
    return "".join(out)


def normalize_text(s: str | None) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = sbc2dbc(s)
    # 去掉所有空白（含中文之间被 OCR 插入的空格）用于比对
    s = re.sub(r"\s+", "", s)
    return s.lower()


def fuzzy_score(a: str, b: str) -> float:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if nb in na or na in nb:
        return 0.95
    return SequenceMatcher(None, na, nb).ratio()


def match_keyword(text: str, keywords: list[str],
                  min_score: float = 0.85) -> tuple[bool, str, float]:
    """返回 (是否命中, 命中的关键词, 分数)。精确包含优先，其次模糊相似度。"""
    nt = normalize_text(text)
    best_kw, best = "", 0.0
    for kw in keywords:
        nk = normalize_text(kw)
        if not nk:
            continue
        if nk == nt:
            return True, kw, 1.0
        if nk in nt:
            # 关键词作为子串出现，长度占比越高分越高
            score = 0.9 + 0.1 * min(1.0, len(nk) / max(len(nt), 1))
            return True, kw, min(score, 1.0)
        sc = SequenceMatcher(None, nt, nk).ratio()
        if sc > best:
            best, best_kw = sc, kw
    if best >= min_score:
        return True, best_kw, best
    return False, "", best


def text_in_set(text: str, words: list[str],
                min_score: float = 0.9) -> bool:
    hit, _, _ = match_keyword(text, words, min_score)
    return hit
