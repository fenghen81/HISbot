"""HISBot 现代视觉主题（反模板化的专业工具风）。

设计取向（design-taste-frontend / read the room）：
- 受众：医院信息科运维，信任优先、可读性优先、accessibility-first。
- 方向：Linear 式克制专业风 —— 纸白底、石墨字、单一深青强调色、克制圆角与间距。
- 刻意避开：靛紫渐变、紫蓝霓虹、过度阴影、千篇一律的亮色“AI 模板感”。

仅样式表，不改任何业务逻辑。
"""
from __future__ import annotations

# 色板（低饱和、对比达标）
INK = "#1A2430"        # 主文字
MUTED = "#5C6B7A"      # 次要文字
PAPER = "#F5F7F8"      # 窗口底
CARD = "#FFFFFF"       # 卡片/输入底
LINE = "#E2E8EE"       # 边框
ACCENT = "#1F6F6B"     # 深青强调（医疗、可信）
ACCENT_HOVER = "#175A56"
ACCENT_SOFT = "#E3F0EF"
DANGER = "#B4453A"

MODERN_QSS = f"""
* {{
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 10.5pt;
    color: {INK};
}}
QMainWindow, QDialog, QWidget {{ background: {PAPER}; }}

/* ---- 顶部品牌条 ---- */
#BrandBar {{ background: {CARD}; border-bottom: 1px solid {LINE}; }}
#BrandTitle {{ font-size: 13pt; font-weight: 700; color: {INK}; }}
#BrandSub {{ font-size: 9pt; color: {MUTED}; }}

/* ---- 页签 ---- */
QTabWidget::pane {{
    border: 1px solid {LINE};
    border-radius: 10px;
    background: {CARD};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {MUTED};
    padding: 8px 18px;
    margin-right: 4px;
    border: none;
    border-radius: 8px;
}}
QTabBar::tab:selected {{
    background: {CARD};
    color: {ACCENT};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{ color: {INK}; background: #ECF0F2; }}

/* ---- 按钮 ---- */
QPushButton {{
    background: {CARD};
    color: {INK};
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: #EFF3F5; border-color: #CBD6DE; }}
QPushButton:pressed {{ background: #E4EAEF; }}
QPushButton[primary="true"] {{
    background: {ACCENT}; color: #FFFFFF; border: none; font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HOVER}; }}

/* ---- 输入控件 ---- */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: {ACCENT_SOFT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 1.5px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}

/* ---- 表格 ---- */
QTableWidget, QTableView {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 10px;
    gridline-color: #EDF1F4;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {INK};
}}
QHeaderView::section {{
    background: #F0F3F5;
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {LINE};
    padding: 7px 10px;
    font-weight: 600;
}}
QTableWidget::item {{ padding: 5px; }}
QTableWidget::item:selected {{ background: {ACCENT_SOFT}; }}

/* ---- 分组/标签 ---- */
QLabel {{ background: transparent; }}
QGroupBox {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 10px;
    margin-top: 12px;
    padding: 10px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {MUTED}; }}

QStatusBar {{ background: {CARD}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QListWidget, QTreeWidget {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 8px; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {INK}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CBD6DE; border-radius: 5px; min-height: 30px; }}
"""
