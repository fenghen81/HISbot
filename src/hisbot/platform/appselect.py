"""“选择 HIS 应用程序”相关的纯逻辑（不依赖 Qt / 具体平台）。

为“首启向导 / 配置页”提供：
- 从系统窗口列表聚合出“正在运行的应用程序”（按可执行路径去重）；
- 由窗口标题推导可直接使用的窗口标题正则；
- 把用户选择映射为 site.yaml 的窗口定位字段并写回。

GUI 只负责交互，所有判定集中在本模块，便于在无显示环境下单测。
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..core.types import WindowInfo

# 命中这些关键词的程序优先排在候选列表前面（仅排序，不做强制过滤）
HIS_HINTS = ("his", "医院", "住院", "门诊", "医生", "护士", "医嘱", "病历",
             "病案", "收费", "药房", "医技", "管理系统", "工作站", "client")

# 选择模式 → site.locate_mode（与 windowing.VALID_MODES 对齐）
MODE_LAUNCH = "launch"
MODE_ACTIVE = "active"
MODE_TITLE = "title"


@dataclass
class CandidateApp:
    """一个“正在运行的应用程序”（同一可执行文件的多个窗口聚合为一项）。"""
    path: str
    exe_name: str
    title: str                       # 代表窗口标题
    pid: int
    window_count: int = 1
    titles: list[str] = field(default_factory=list)
    is_his_like: bool = False

    def display(self) -> str:
        tag = "疑似HIS　" if self.is_his_like else ""
        return f"{tag}{self.title}　[{self.exe_name}]"


def exe_basename(path: str) -> str:
    name = os.path.basename(path or "")
    return name


def _score(cand: CandidateApp) -> tuple:
    """排序键：疑似 HIS 优先，其次窗口多、标题长。"""
    hay = (cand.exe_name + " " + cand.title).lower()
    hint = 0 if any(h in hay for h in HIS_HINTS) else 1
    return (hint, -cand.window_count, -len(cand.title), cand.exe_name.lower())


def build_candidates(windows: Iterable[WindowInfo],
                     path_for_pid: Callable[[int], str]
                     ) -> list[CandidateApp]:
    """把窗口列表聚合成按可执行路径去重的候选程序列表。

    - 取不到可执行路径的窗口忽略（无法回填“启动路径”）；
    - 同一 exe 路径的多个窗口合并，窗口最多/标题最具代表性的作为代表；
    - 疑似 HIS 的排最前。
    """
    by_path: dict[str, CandidateApp] = {}
    for w in windows:
        if not w.title:
            continue
        path = (path_for_pid(w.pid) or "").strip()
        if not path:
            continue
        key = os.path.normcase(os.path.normpath(path))
        cand = by_path.get(key)
        if cand is None:
            cand = CandidateApp(path=path, exe_name=exe_basename(path),
                                title=w.title, pid=w.pid or 0,
                                titles=[w.title])
            by_path[key] = cand
        else:
            cand.window_count += 1
            if w.title not in cand.titles:
                cand.titles.append(w.title)
            # 代表标题取更长、信息量更大者
            if len(w.title) > len(cand.title):
                cand.title = w.title
            if not cand.pid and w.pid:
                cand.pid = w.pid
    out = list(by_path.values())
    for c in out:
        hay = (c.exe_name + " " + c.title).lower()
        c.is_his_like = any(h in hay for h in HIS_HINTS)
    out.sort(key=_score)
    return out


def list_running_apps(capturer) -> list[CandidateApp]:
    """薄封装：直接基于平台 capturer 枚举正在运行的 GUI 程序。"""
    return build_candidates(capturer.list_windows(),
                            capturer.process_path)


# ----------------------------------------------------------------------- #
# 标题 → 正则
# ----------------------------------------------------------------------- #
def derive_title_pattern(title: str) -> str:
    """把一个具体窗口标题转成可安全用于 re.search 的正则。

    默认转义整标题（精确、不会误点别的窗口）；标题里的空白序列宽松化为
    \\s+，容忍全/半角空格与细微差异。空标题返回空串。
    """
    t = (title or "").strip()
    if not t:
        return ""
    parts = re.split(r"\s+", t)
    return r"\s+".join(re.escape(p) for p in parts if p)


def title_pattern_preview(title: str) -> str:
    """给向导展示“宽松关键词”备选（取标题中的中/英/数字片段，用 | 连接）。"""
    chunks = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]{2,}", title or "")
    seen, uniq = set(), []
    for c in chunks:
        if c.lower() not in seen and len(c) >= 2:
            seen.add(c.lower())
            uniq.append(re.escape(c))
    return "|".join(uniq[:6])


# ----------------------------------------------------------------------- #
# 选择 → site 配置
# ----------------------------------------------------------------------- #
def apply_window_choice(site: dict, mode: str, *,
                        program_path: str = "",
                        program_args: str = "",
                        work_dir: str = "",
                        title_pattern: str = "",
                        launch_wait_s: float = 8.0) -> dict:
    """把用户选择写入 site 配置（就地更新 site["site"] 并返回该节点）。

    mode:
    - launch：填程序路径/参数/工作目录 + 标题规则，locate_mode=launch；
    - active：locate_mode=active（标题规则留作参考）；
    - title ：locate_mode=title，仅写标题规则。
    """
    node = site.setdefault("site", {})
    mode = mode if mode in (MODE_LAUNCH, MODE_ACTIVE, MODE_TITLE) \
        else MODE_TITLE
    node["locate_mode"] = mode
    node["setup_done"] = True
    node.pop("setup_dismissed", None)
    if title_pattern:
        node["window_title_pattern"] = title_pattern
    if mode == MODE_LAUNCH:
        node["program_path"] = program_path.strip()
        node["program_args"] = program_args.strip()
        node["work_dir"] = work_dir.strip()
        try:
            node["launch_wait_s"] = int(float(launch_wait_s))
        except (TypeError, ValueError):
            node["launch_wait_s"] = 8
    return node


def is_setup_complete(site: dict) -> bool:
    """是否已完成 HIS 目标的首次确认（决定首启是否还要弹向导）。

    以显式标记为准（与字段是否已填解耦，确保出厂首次启动一定引导一次）：
    - setup_done=true：向导已确认；
    - setup_dismissed=true：用户选择“稍后手动配置”。
    之后均可在配置页重新打开向导。
    """
    node = site.get("site", {}) if isinstance(site, dict) else {}
    return bool(node.get("setup_done") or node.get("setup_dismissed"))
