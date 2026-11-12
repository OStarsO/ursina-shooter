# -*- coding: utf-8 -*-
"""射击启动器 · 共享样式常量

launcher.py 与 net_ui.py 共同引用，避免相互导入形成环。
"""

# 配色（战术风深色）
C_BG = "#0A0D12"
C_PANEL = "#111722"
C_PANEL_2 = "#0D131C"
C_BORDER = "#1E2836"
C_TEXT = "#E7EEF9"
C_MUTED = "#7E8DA4"
C_ACCENT = "#FF6B35"
C_ACCENT_DIM = "#8C3A1D"
C_OK = "#3DDC97"
C_WARN = "#F5B544"
C_BAD = "#FF4D5E"
C_INFO = "#38BDF8"

# 队伍色（红队 / 蓝队，沿用股市涨红跌绿的反向习惯：红=我方强调色）
C_TEAM_RED = "#FF5A5F"
C_TEAM_BLUE = "#38BDF8"

FONT_FAMILY = "Microsoft YaHei UI"
FONT_FAMILY_MONO = "Consolas"

# 常用控件样式（字符串模板，各窗口 setStyleSheet 用）
GHOST_BTN_QSS = f"""
    QPushButton#Ghost {{
        background: transparent;
        border: 1px solid {C_BORDER};
        border-radius: 8px;
        padding: 6px 12px;
        color: {C_MUTED};
    }}
    QPushButton#Ghost:hover {{
        border-color: {C_ACCENT};
        color: {C_TEXT};
    }}
    QPushButton#Ghost:pressed {{ background: #16202D; }}
"""

LINE_EDIT_QSS = f"""
    QLineEdit {{
        background: {C_PANEL_2};
        border: 1px solid {C_BORDER};
        border-radius: 8px;
        padding: 7px 10px;
        color: {C_TEXT};
        selection-background-color: {C_ACCENT_DIM};
    }}
    QLineEdit:focus {{ border-color: {C_ACCENT}; }}
"""

COMBO_QSS = f"""
    QComboBox {{
        background: {C_PANEL_2};
        border: 1px solid {C_BORDER};
        border-radius: 8px;
        padding: 5px 10px;
        min-width: 100px;
        color: {C_TEXT};
    }}
    QComboBox:hover {{ border-color: #33445C; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {C_PANEL};
        border: 1px solid {C_BORDER};
        selection-background-color: {C_ACCENT_DIM};
        outline: none;
    }}
"""

LOG_BOX_QSS = f"""
    QTextEdit#LogBox {{
        background: {C_PANEL_2};
        border: 1px solid {C_BORDER};
        border-radius: 10px;
        color: #9FB0C8;
        padding: 8px;
    }}
    QTextEdit#ConsoleBox {{
        background: #0B1017;
        border: 1px solid {C_BORDER};
        border-radius: 10px;
        color: #B7C4D6;
        padding: 8px;
    }}
"""

SPINBOX_QSS = f"""
    QSpinBox {{
        background: {C_PANEL_2};
        border: 1px solid {C_BORDER};
        border-radius: 8px;
        padding: 5px 8px;
        color: {C_TEXT};
    }}
    QSpinBox:focus {{ border-color: {C_ACCENT}; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: transparent; border: none; width: 16px;
    }}
"""
