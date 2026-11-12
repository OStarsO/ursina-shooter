# -*- coding: utf-8 -*-
"""射击启动器 · 登录 / 模式选择 / 联机大厅界面

依赖 app_style（配色）与 room_net（房间服务），不反向依赖 launcher，
避免循环导入：launcher 只负责把启动回调传进来。
"""

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFont, QLinearGradient, QPainterPath,
)
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QLineEdit, QListWidget, QListWidgetItem, QComboBox, QSpinBox, QTextEdit,
    QGridLayout, QSizePolicy, QGraphicsDropShadowEffect, QMessageBox,
)

import room_net as rn
from app_style import (
    C_BG, C_PANEL, C_PANEL_2, C_BORDER, C_TEXT, C_MUTED, C_ACCENT, C_ACCENT_DIM,
    C_OK, C_WARN, C_BAD, C_INFO, C_TEAM_RED, C_TEAM_BLUE,
    FONT_FAMILY, FONT_FAMILY_MONO,
    GHOST_BTN_QSS, LINE_EDIT_QSS, COMBO_QSS, LOG_BOX_QSS, SPINBOX_QSS,
)

MODE_TEXT = {
    "training": "训练场模式",
    "duel": "单挑模式",
    "team": "团队竞技",
}

TEAM_LABEL = {"red": "红队", "blue": "蓝队"}


# ============================ 公共样式与组件 ============================

def base_qss():
    return f"""
        QWidget {{
            color: {C_TEXT};
            font-family: "{FONT_FAMILY}";
            font-size: 12px;
        }}
        QLabel#CardTitle {{
            color: {C_MUTED};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 1px;
        }}
        QLabel#Hint {{ color: {C_MUTED}; font-size: 11px; }}
        QLabel#Error {{ color: {C_BAD}; font-size: 11px; }}
        QLabel#Title {{
            color: {C_TEXT};
            font-size: 20px;
            font-weight: 700;
        }}
        QLabel#SubTitle {{ color: {C_MUTED}; font-size: 11px; letter-spacing: 2px; }}
        QPushButton#Primary {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {C_ACCENT}, stop:1 #FF8B57);
            color: #1A0D06;
            border: none;
            border-radius: 10px;
            padding: 9px 22px;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 1px;
        }}
        QPushButton#Primary:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #FF7B4B, stop:1 #FFA070);
        }}
        QPushButton#Primary:pressed {{ background: #E05A28; }}
        QPushButton#Primary:disabled {{ background: #2A3342; color: {C_MUTED}; }}
        QPushButton#Danger {{
            background: transparent;
            border: 1px solid #5A2634;
            color: #FF8A96;
            border-radius: 8px;
            padding: 6px 14px;
        }}
        QPushButton#Danger:hover {{ background: #2A1620; }}
        QListWidget {{
            background: {C_PANEL_2};
            border: 1px solid {C_BORDER};
            border-radius: 10px;
            padding: 4px;
            outline: none;
        }}
        QListWidget::item {{
            background: transparent;
            border-radius: 8px;
            padding: 2px;
            margin: 2px 0;
        }}
        QListWidget::item:selected {{ background: #1B2534; }}
        QListWidget::item:hover {{ background: #161F2C; }}
    """ + GHOST_BTN_QSS + LINE_EDIT_QSS + COMBO_QSS + LOG_BOX_QSS + SPINBOX_QSS


def add_glow(widget, color=C_ACCENT, radius=26, alpha=110):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(radius)
    effect.setOffset(0, 4)
    c = QColor(color)
    c.setAlpha(alpha)
    effect.setColor(c)
    widget.setGraphicsEffect(effect)


class FramelessMixin:
    """无边框圆角窗口：拖动 + 绘制背景"""

    def init_frameless(self, radius=16):
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag = None
        self._radius = radius
        self.setStyleSheet(base_qss())

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QColor(C_BG))
        grad.setColorAt(1, QColor("#070A0F"))
        p.fillPath(path, grad)
        p.setPen(QPen(QColor("#232E3E"), 1))
        p.drawPath(path)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag = None
        super().mouseReleaseEvent(event)


class CardFrame(QFrame):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(f"QFrame#Card {{ background:{C_PANEL}; border:1px solid {C_BORDER}; border-radius:14px; }}")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 12, 16, 14)
        self.body.setSpacing(8)
        self.head = QHBoxLayout()
        self.head.setSpacing(8)
        if title:
            lbl = QLabel(title)
            lbl.setObjectName("CardTitle")
            self.head.addWidget(lbl)
            self.head.addStretch(1)
            self.body.addLayout(self.head)
        self.content = QVBoxLayout()
        self.content.setSpacing(6)
        self.body.addLayout(self.content)


class TitleBar(QWidget):
    """对话框顶部：标题 + 关闭"""

    def __init__(self, title, parent=None, extra=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("CardTitle")
        lay.addWidget(label)
        lay.addStretch(1)
        if extra is not None:
            lay.addWidget(extra)
        btn = QPushButton("✕")
        btn.setObjectName("WindowBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(26, 24)
        btn.setStyleSheet(f"QPushButton#WindowBtn{{background:transparent;border:none;color:{C_MUTED};}}"
                          f"QPushButton#WindowBtn:hover{{background:#C0392B;color:white;border-radius:6px;}}")
        btn.clicked.connect(parent.reject if hasattr(parent, "reject") else parent.close)
        lay.addWidget(btn)


# ============================ 登录 ============================

class LoginDialog(FramelessMixin, QDialog):
    """启动后第一屏：游客登录（邮箱登录位预留）"""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.nickname = ""
        self.setWindowTitle("登录")
        self.setFixedSize(460, 400)
        self.init_frameless(18)
        self._build()
        self.nickname_edit.setFocus()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 26)
        root.setSpacing(10)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        mark = QLabel("◎")
        mark.setStyleSheet(f"color:{C_ACCENT}; font-size:26px;")
        brand_row.addWidget(mark)
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        t = QLabel("射 击")
        t.setObjectName("Title")
        title_col.addWidget(t)
        sub = QLabel("SHOOTER  ·  客户端")
        sub.setObjectName("SubTitle")
        title_col.addWidget(sub)
        brand_row.addLayout(title_col)
        brand_row.addStretch(1)
        self.title_bar = TitleBar("", self)
        brand_row.addWidget(self.title_bar)
        root.addLayout(brand_row)

        root.addSpacing(6)

        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self.tab_guest = QPushButton("游客登录")
        self.tab_email = QPushButton("邮箱登录")
        for btn, active in ((self.tab_guest, True), (self.tab_email, False)):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._tab_qss(active))
            tabs.addWidget(btn)
        tabs.addStretch(1)
        root.addLayout(tabs)

        self.hint_email = QLabel("邮箱登录即将开放：后续版本支持注册/登录与云端存档")
        self.hint_email.setObjectName("Hint")
        root.addWidget(self.hint_email)

        root.addSpacing(4)
        root.addWidget(self._label("昵称"))
        self.nickname_edit = QLineEdit(self.cfg.get("nickname", ""))
        self.nickname_edit.setPlaceholderText("输入昵称，例如：Ghost_07")
        self.nickname_edit.setMaxLength(12)
        self.nickname_edit.returnPressed.connect(self._submit)
        root.addWidget(self.nickname_edit)

        self.err = QLabel("")
        self.err.setObjectName("Error")
        self.err.setFixedHeight(16)
        root.addWidget(self.err)

        hint = QLabel("昵称会显示在房间玩家列表与对战比分中，可随时修改")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addStretch(1)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        quit_btn = QPushButton("退出")
        quit_btn.setObjectName("Ghost")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.clicked.connect(self.reject)
        btns.addWidget(quit_btn)
        btns.addStretch(1)
        self.btn_enter = QPushButton("以游客身份进入")
        self.btn_enter.setObjectName("Primary")
        self.btn_enter.setCursor(Qt.PointingHandCursor)
        self.btn_enter.setFixedHeight(40)
        self.btn_enter.setMinimumWidth(170)
        self.btn_enter.clicked.connect(self._submit)
        btns.addWidget(self.btn_enter)
        root.addLayout(btns)

    @staticmethod
    def _tab_qss(active):
        if active:
            return (f"QPushButton{{background:{C_ACCENT_DIM}; border:1px solid {C_ACCENT};"
                    f"color:{C_TEXT}; border-radius:8px; padding:6px 16px; font-weight:600;}}")
        return (f"QPushButton{{background:transparent; border:1px solid {C_BORDER};"
                f"color:{C_MUTED}; border-radius:8px; padding:6px 16px;}}"
                f"QPushButton:hover{{border-color:#33445C; color:{C_TEXT};}}")

    @staticmethod
    def _label(text):
        lbl = QLabel(text)
        lbl.setObjectName("Hint")
        return lbl

    def _submit(self):
        name = self.nickname_edit.text().strip()
        if not name:
            self.err.setText("请输入昵称")
            self.nickname_edit.setFocus()
            return
        if len(name) > 12:
            self.err.setText("昵称最长 12 个字符")
            return
        if name.lower() in ("all", "全员", "系统", "system"):
            self.err.setText("该昵称被系统保留，请换一个")
            return
        self.nickname = name
        self.accept()


# ============================ 模式选择 ============================

class ModeCard(QFrame):
    clicked = Signal(str)

    def __init__(self, mode, title, subtitle, detail, accent=C_ACCENT, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.accent = accent
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(236, 176)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        icon = QLabel({"training": "◎", "duel": "✜", "team": "❖"}.get(mode, "◎"))
        icon.setStyleSheet(f"color:{accent}; font-size:26px;")
        lay.addWidget(icon)
        t = QLabel(title)
        t.setStyleSheet(f"color:{C_TEXT}; font-size:17px; font-weight:700;")
        lay.addWidget(t)
        s = QLabel(subtitle)
        s.setStyleSheet(f"color:{accent}; font-size:11px; letter-spacing:1px;")
        lay.addWidget(s)
        d = QLabel(detail)
        d.setObjectName("Hint")
        d.setWordWrap(True)
        lay.addWidget(d)
        lay.addStretch(1)

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        fill = QColor("#141C28") if self._hover else QColor(C_PANEL)
        p.fillPath(path, fill)
        p.setPen(QPen(QColor(self.accent if self._hover else C_BORDER), 1.2 if self._hover else 1))
        p.drawPath(path)
        super().paintEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.mode)
        super().mousePressEvent(event)


class ModeSelectDialog(FramelessMixin, QDialog):
    """开始游戏后：训练场 / 单挑 / 团队竞技"""

    def __init__(self, nickname="", parent=None):
        super().__init__(parent)
        self.mode = ""
        self.setWindowTitle("选择模式")
        self.setFixedSize(880, 420)
        self.init_frameless(18)
        self._build(nickname)

    def _build(self, nickname):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(12)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("选择游戏模式")
        t.setObjectName("Title")
        col.addWidget(t)
        sub = QLabel(f"当前玩家：{nickname}    训练场为本地单机，单挑/团队为局域网联机")
        sub.setObjectName("Hint")
        col.addWidget(sub)
        head.addLayout(col)
        head.addStretch(1)
        head.addWidget(TitleBar("", self))
        root.addLayout(head)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.card_training = ModeCard("training", "训练场模式", "TRAINING · 本地",
                                      "单人练习，打靶计分，不需要网络。直接启动游戏。")
        self.card_duel = ModeCard("duel", "单挑模式", "DUEL · 1v1",
                                  "局域网 1v1 对抗。需要创建房间或加入好友的房间。", C_INFO)
        self.card_team = ModeCard("team", "团队竞技", "TEAM · 5v5 / 10v10",
                                  "红蓝两队对战，建房时选择 5v5 或 10v10 规模。", C_TEAM_BLUE)
        for card in (self.card_training, self.card_duel, self.card_team):
            card.clicked.connect(self._choose)
            card.setFixedHeight(216)
            cards.addWidget(card, 1)
        root.addLayout(cards)
        root.addStretch(1)

        foot = QHBoxLayout()
        tip = QLabel("提示：联机需要双方在同一局域网，房主机器需放行防火墙 25250 端口（专用网络）")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        foot.addWidget(tip, 1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        root.addLayout(foot)

    def _choose(self, mode):
        self.mode = mode
        self.accept()


# ============================ 联机方式 ============================

class NetModeDialog(FramelessMixin, QDialog):
    """单挑/团队：创建房间 或 加入房间"""

    def __init__(self, mode_label, parent=None):
        super().__init__(parent)
        self.choice = ""
        self.setWindowTitle("联机方式")
        self.setFixedSize(760, 380)
        self.init_frameless(18)
        self._build(mode_label)

    def _build(self, mode_label):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(12)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("联机方式")
        t.setObjectName("Title")
        col.addWidget(t)
        sub = QLabel(f"{mode_label} · 局域网联机（TCP 25250）")
        sub.setObjectName("Hint")
        col.addWidget(sub)
        head.addLayout(col)
        head.addStretch(1)
        head.addWidget(TitleBar("", self))
        root.addLayout(head)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        for mode, title, sub, detail, accent in (
            ("host", "创建房间", "HOST · 本机监听 25250",
             "启动房间服务并成为房主：可设密码、调比分、开控制台作弊，准备好后点开始。", C_ACCENT),
            ("join", "加入房间", "JOIN · 连接房主",
             "扫描局域网内 25250 端口的房间，也可直接输入房主 IP 加入。", C_INFO),
        ):
            card = ModeCard(mode, title, sub, detail, accent)
            card.clicked.connect(self._choose)
            card.setFixedHeight(196)
            cards.addWidget(card, 1)
        root.addLayout(cards)
        root.addStretch(1)

        foot = QHBoxLayout()
        back = QPushButton("返回")
        back.setObjectName("Ghost")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.reject)
        foot.addWidget(back)
        foot.addStretch(1)
        root.addLayout(foot)

    def _choose(self, choice):
        self.choice = choice
        self.accept()


# ============================ 创建房间 ============================

class CreateRoomDialog(FramelessMixin, QDialog):
    """房主建房：房间名、规模、密码、比分/时长预配置"""

    def __init__(self, nickname, mode, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.config = None
        self.setWindowTitle("创建房间")
        self.setFixedSize(640, 470)
        self.init_frameless(18)
        self._build(nickname)

    def _build(self, nickname):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 22, 30, 22)
        root.setSpacing(10)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("创建房间")
        t.setObjectName("Title")
        col.addWidget(t)
        sub = QLabel(f"本机将监听 TCP 25250，房主：{nickname}")
        sub.setObjectName("Hint")
        col.addWidget(sub)
        head.addLayout(col)
        head.addStretch(1)
        head.addWidget(TitleBar("", self))
        root.addLayout(head)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        row = 0
        form.addWidget(self._label("房间名"), row, 0)
        self.edit_name = QLineEdit(f"{nickname}的房间")
        self.edit_name.setMaxLength(20)
        form.addWidget(self.edit_name, row, 1, 1, 3)
        row += 1

        if self.mode == "team":
            form.addWidget(self._label("团队规模"), row, 0)
            self.combo_size = QComboBox()
            self.combo_size.addItem("5v5（10 人）", "team5")
            self.combo_size.addItem("10v10（20 人）", "team10")
            form.addWidget(self.combo_size, row, 1)
            row += 1

        form.addWidget(self._label("房间密码"), row, 0)
        self.edit_pwd = QLineEdit()
        self.edit_pwd.setPlaceholderText("留空表示无密码")
        self.edit_pwd.setMaxLength(24)
        form.addWidget(self.edit_pwd, row, 1, 1, 3)
        row += 1

        form.addWidget(self._label("目标比分"), row, 0)
        self.spin_score = QSpinBox()
        self.spin_score.setRange(0, 999)
        self.spin_score.setValue(0)
        self.spin_score.setSpecialValueText("不限")
        form.addWidget(self.spin_score, row, 1)
        hint1 = QLabel("先到该比分结束（0 = 不限）")
        hint1.setObjectName("Hint")
        form.addWidget(hint1, row, 2, 1, 2)
        row += 1

        form.addWidget(self._label("比赛时长"), row, 0)
        self.combo_time = QComboBox()
        for text, sec in (("不限时", 0), ("5 分钟", 300), ("10 分钟", 600),
                          ("15 分钟", 900), ("30 分钟", 1800)):
            self.combo_time.addItem(text, sec)
        self.combo_time.setCurrentIndex(2)
        form.addWidget(self.combo_time, row, 1)
        hint2 = QLabel("房主可随时用控制台 time 命令修改")
        hint2.setObjectName("Hint")
        form.addWidget(hint2, row, 2, 1, 2)
        row += 1

        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        root.addLayout(form)

        tip = QLabel("创建后房间即刻开始监听，好友可在“加入房间”里扫到；"
                     "若对方连不上，请把本机网络设为“专用网络”或允许 25250 入站。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        root.addWidget(tip)
        root.addStretch(1)

        btns = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addStretch(1)
        create = QPushButton("创建并进入房间")
        create.setObjectName("Primary")
        create.setCursor(Qt.PointingHandCursor)
        create.setFixedHeight(40)
        create.clicked.connect(self._submit)
        btns.addWidget(create)
        root.addLayout(btns)

    @staticmethod
    def _label(text):
        lbl = QLabel(text)
        lbl.setObjectName("Hint")
        lbl.setFixedWidth(64)
        return lbl

    def _submit(self):
        name = self.edit_name.text().strip() or "未命名房间"
        config = {
            "room_name": name,
            "mode": self.combo_size.currentData() if self.mode == "team" else self.mode,
            "password": self.edit_pwd.text().strip(),
            "score_target": self.spin_score.value(),
            "time_limit": self.combo_time.currentData(),
        }
        self.config = config
        self.accept()


# ============================ 加入房间 ============================

class ScanThread(QThread):
    progress = Signal(int)
    done = Signal(list)

    def __init__(self, timeout=0.5, parent=None):
        super().__init__(parent)
        self.timeout = timeout

    def run(self):
        counter = {"n": 0, "last": 0}

        def cb(ip):
            counter["n"] += 1
            if counter["n"] - counter["last"] >= 40:
                counter["last"] = counter["n"]
                self.progress.emit(counter["n"])

        try:
            rooms = rn.scan_lan(timeout=self.timeout, progress=cb)
        except Exception:  # noqa: BLE001
            rooms = []
        self.done.emit(rooms)


class JoinThread(QThread):
    done = Signal(object, str)  # (RoomClient, error)

    def __init__(self, nickname, ip, password="", parent=None):
        super().__init__(parent)
        self.nickname = nickname
        self.ip = ip
        self.password = password

    def run(self):
        client = rn.RoomClient(self.nickname)
        try:
            client.connect(self.ip, self.password, timeout=5.0)
            self.done.emit(client, "")
        except rn.RoomError as exc:
            client.close()
            self.done.emit(None, str(exc))


class PasswordDialog(FramelessMixin, QDialog):
    def __init__(self, room_name, parent=None, hint=None, echo=QLineEdit.Password):
        super().__init__(parent)
        self.password = ""
        self.setWindowTitle("房间密码")
        self.setFixedSize(400, 230)
        self.init_frameless(16)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel("输入房间密码")
        t.setObjectName("Title")
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(TitleBar("", self))
        root.addLayout(head)
        hint = hint or f"房间「{room_name}」已加密"
        hint_lbl = QLabel(hint)
        hint_lbl.setObjectName("Hint")
        hint_lbl.setWordWrap(True)
        root.addWidget(hint_lbl)
        self.edit = QLineEdit()
        self.edit.setEchoMode(echo)
        self.edit.setPlaceholderText("房间密码" if echo == QLineEdit.Password else "留空表示取消密码")
        self.edit.returnPressed.connect(self._submit)
        root.addWidget(self.edit)
        root.addStretch(1)
        btns = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addStretch(1)
        ok = QPushButton("确定")
        ok.setObjectName("Primary")
        ok.clicked.connect(self._submit)
        btns.addWidget(ok)
        root.addLayout(btns)
        self.edit.setFocus()

    def _submit(self):
        self.password = self.edit.text()
        self.accept()


class JoinRoomDialog(FramelessMixin, QDialog):
    """加入房间：扫描本网段 + 手动输入 IP"""

    def __init__(self, nickname, parent=None):
        super().__init__(parent)
        self.nickname = nickname
        self.client = None
        self.joined_room = None
        self._scan_thread = None
        self._join_thread = None
        self.setWindowTitle("加入房间")
        self.setFixedSize(720, 600)
        self.init_frameless(18)
        self._build()
        QTimer.singleShot(120, self.start_scan)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(10)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("加入房间")
        t.setObjectName("Title")
        col.addWidget(t)
        sub = QLabel("扫描局域网内监听 25250 的房间，或直接输入房主 IP")
        sub.setObjectName("Hint")
        col.addWidget(sub)
        head.addLayout(col)
        head.addStretch(1)
        head.addWidget(TitleBar("", self))
        root.addLayout(head)

        scan_row = QHBoxLayout()
        scan_row.setSpacing(8)
        self.lbl_scan = QLabel("准备扫描…")
        self.lbl_scan.setObjectName("Hint")
        scan_row.addWidget(self.lbl_scan, 1)
        self.btn_scan = QPushButton("重新扫描")
        self.btn_scan.setObjectName("Ghost")
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.clicked.connect(self.start_scan)
        scan_row.addWidget(self.btn_scan)
        root.addLayout(scan_row)

        self.list_rooms = QListWidget()
        self.list_rooms.itemDoubleClicked.connect(lambda _i: self._join_selected())
        root.addWidget(self.list_rooms, 1)

        manual = QHBoxLayout()
        manual.setSpacing(8)
        manual.addWidget(QLabel("房主 IP"))
        self.edit_ip = QLineEdit()
        self.edit_ip.setPlaceholderText("例如 192.168.1.20（端口固定 25250）")
        manual.addWidget(self.edit_ip, 1)
        self.btn_join_ip = QPushButton("连接")
        self.btn_join_ip.setObjectName("Ghost")
        self.btn_join_ip.setCursor(Qt.PointingHandCursor)
        self.btn_join_ip.clicked.connect(self._join_manual)
        manual.addWidget(self.btn_join_ip)
        root.addLayout(manual)

        self.lbl_tip = QLabel("密码房会自动提示输入密码；连接失败请检查双方是否在同一局域网。")
        self.lbl_tip.setObjectName("Hint")
        self.lbl_tip.setWordWrap(True)
        root.addWidget(self.lbl_tip)

        btns = QHBoxLayout()
        back = QPushButton("返回")
        back.setObjectName("Ghost")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.reject)
        btns.addWidget(back)
        btns.addStretch(1)
        self.btn_join = QPushButton("加入选中房间")
        self.btn_join.setObjectName("Primary")
        self.btn_join.setCursor(Qt.PointingHandCursor)
        self.btn_join.setFixedHeight(38)
        self.btn_join.setEnabled(False)
        self.btn_join.clicked.connect(self._join_selected)
        btns.addWidget(self.btn_join)
        root.addLayout(btns)

        self.list_rooms.itemSelectionChanged.connect(
            lambda: self.btn_join.setEnabled(self.list_rooms.currentItem() is not None)
        )

    # ---------- 扫描 ----------

    def start_scan(self):
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self.list_rooms.clear()
        self.btn_scan.setEnabled(False)
        self.btn_join.setEnabled(False)
        self.lbl_scan.setText("正在扫描本网段 25250 端口…")
        self._scan_thread = ScanThread(0.5, self)
        self._scan_thread.progress.connect(
            lambda n: self.lbl_scan.setText(f"正在扫描… 已探测 {n} 个地址")
        )
        self._scan_thread.done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, rooms):
        self.btn_scan.setEnabled(True)
        self.list_rooms.clear()
        if not rooms:
            self.lbl_scan.setText("未发现房间：确认房主已创建房间，或手动输入房主 IP")
            return
        self.lbl_scan.setText(f"发现 {len(rooms)} 个房间")
        for room in rooms:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, room)
            widget = self._room_row(room)
            item.setSizeHint(widget.sizeHint())
            self.list_rooms.addItem(item)
            self.list_rooms.setItemWidget(item, widget)

    def _room_row(self, room):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        name = QLabel(room.get("name", "房间"))
        name.setStyleSheet(f"color:{C_TEXT}; font-size:13px; font-weight:600;")
        name.setMinimumWidth(170)
        lay.addWidget(name)
        mode = QLabel(room.get("mode_label", ""))
        mode.setStyleSheet(f"color:{C_INFO}; font-size:11px;")
        mode.setMinimumWidth(96)
        lay.addWidget(mode)
        players = QLabel(f"{room.get('players', 0)}/{room.get('max_players', 0)} 人")
        players.setStyleSheet(f"color:{C_MUTED}; font-size:11px;")
        players.setMinimumWidth(64)
        lay.addWidget(players)
        if room.get("has_pwd"):
            lock = QLabel("🔒 密码")
            lock.setStyleSheet(f"color:{C_WARN}; font-size:11px;")
            lay.addWidget(lock)
        if room.get("locked"):
            lock2 = QLabel("已锁定")
            lock2.setStyleSheet(f"color:{C_BAD}; font-size:11px;")
            lay.addWidget(lock2)
        lay.addStretch(1)
        ip = QLabel(room.get("ip", ""))
        ip.setStyleSheet(f"color:{C_MUTED}; font-family:{FONT_FAMILY_MONO}; font-size:11px;")
        lay.addWidget(ip)
        return w

    # ---------- 加入 ----------

    def _join_selected(self):
        item = self.list_rooms.currentItem()
        if item is None:
            return
        room = item.data(Qt.UserRole)
        if room.get("locked"):
            QMessageBox.information(self, "无法加入", "该房间已锁定，禁止新玩家加入。")
            return
        pwd = ""
        if room.get("has_pwd"):
            dlg = PasswordDialog(room.get("name", "房间"), self)
            if dlg.exec() != QDialog.Accepted:
                return
            pwd = dlg.password
        self._do_join(room.get("ip", ""), pwd, room)

    def _join_manual(self):
        ip = self.edit_ip.text().strip()
        if not ip:
            self.lbl_tip.setText("请输入房主 IP")
            return
        info = rn.query_room(ip, timeout=1.2)
        if info is None:
            self.lbl_tip.setText(f"{ip}:25250 没有响应，确认房主已建房且防火墙已放行")
            return
        if info.get("locked"):
            self.lbl_tip.setText("该房间已锁定，禁止新玩家加入")
            return
        pwd = ""
        if info.get("has_pwd"):
            dlg = PasswordDialog(info.get("name", "房间"), self)
            if dlg.exec() != QDialog.Accepted:
                return
            pwd = dlg.password
        self._do_join(ip, pwd, info)

    def _do_join(self, ip, password, info):
        if self._join_thread and self._join_thread.isRunning():
            return
        self.btn_join.setEnabled(False)
        self.btn_join_ip.setEnabled(False)
        self.lbl_tip.setText(f"正在加入 {ip} …")
        self._join_thread = JoinThread(self.nickname, ip, password, self)
        self._join_thread.done.connect(lambda client, err: self._on_join_done(client, err, info))
        self._join_thread.start()

    def _on_join_done(self, client, error, info):
        self.btn_join.setEnabled(True)
        self.btn_join_ip.setEnabled(True)
        if client is None:
            self.lbl_tip.setText(f"加入失败：{error}")
            return
        self.client = client
        self.joined_room = client.room or info
        self.accept()


# ============================ 房间大厅 ============================

class LobbySidePanel(QWidget):
    """大厅左侧：房间名、模式、人数、状态"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        self.room_name = "房间"
        self.mode_label = ""
        self.count_text = "1 / 2"
        self.state_text = "等待玩家"
        self.role_text = "房主"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _tick(self):
        self._phase += 0.06
        self.update()

    def update_info(self, name=None, mode=None, count=None, state=None, role=None):
        if name is not None:
            self.room_name = name
        if mode is not None:
            self.mode_label = mode
        if count is not None:
            self.count_text = count
        if state is not None:
            self.state_text = state
        if role is not None:
            self.role_text = role
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, w + 16, h, 16, 16)
        p.setClipPath(clip)
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, QColor("#131B29"))
        grad.setColorAt(0.6, QColor("#0C1119"))
        grad.setColorAt(1, QColor("#090C11"))
        p.fillRect(self.rect(), grad)

        p.setPen(QPen(QColor(255, 255, 255, 8), 1))
        for x in range(0, w, 28):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, 28):
            p.drawLine(0, y, w, y)

        # 顶部状态灯
        p.setPen(Qt.NoPen)
        pulse = 0.5 + 0.5 * abs((self._phase % 2) - 1)
        dot = QColor(C_OK)
        dot.setAlpha(int(70 + 120 * pulse))
        p.setBrush(dot)
        p.drawEllipse(w - 42, 34, 8, 8)
        p.setBrush(QColor(C_OK))
        p.drawEllipse(w - 42, 34, 8, 8)

        # 房间名
        p.setPen(QColor(C_MUTED))
        f = QFont(FONT_FAMILY)
        f.setPixelSize(10)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(f)
        p.drawText(30, 46, self.role_text.upper() + " · ROOM")

        p.setPen(QColor(C_TEXT))
        f2 = QFont(FONT_FAMILY)
        f2.setPixelSize(26)
        f2.setWeight(QFont.Bold)
        p.setFont(f2)
        name = self.room_name if len(self.room_name) <= 12 else self.room_name[:12] + "…"
        p.drawText(28, 96, name)

        p.setPen(QColor(C_ACCENT))
        f3 = QFont(FONT_FAMILY)
        f3.setPixelSize(12)
        f3.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(f3)
        p.drawText(30, 124, self.mode_label)

        # 人数与状态
        p.setPen(QColor(C_MUTED))
        f4 = QFont(FONT_FAMILY)
        f4.setPixelSize(10)
        p.setFont(f4)
        p.drawText(30, h - 150, "玩家")
        p.setPen(QColor(C_TEXT))
        f5 = QFont(FONT_FAMILY_MONO)
        f5.setPixelSize(30)
        p.setFont(f5)
        p.drawText(28, h - 112, self.count_text)

        p.setPen(QColor(C_MUTED))
        p.setFont(f4)
        p.drawText(30, h - 80, "房间状态")
        p.setPen(QColor(C_OK if self.state_text in ("等待玩家", "大厅") else C_WARN))
        f6 = QFont(FONT_FAMILY)
        f6.setPixelSize(14)
        p.setFont(f6)
        p.drawText(30, h - 58, self.state_text)

        # 端口提示
        p.setPen(QColor(C_MUTED))
        f7 = QFont(FONT_FAMILY_MONO)
        f7.setPixelSize(10)
        p.setFont(f7)
        p.drawText(30, h - 28, "TCP 25250  ·  LAN")


class MemberRow(QWidget):
    def __init__(self, member, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(8)
        color = C_TEAM_RED if member.get("team") == "red" else C_TEAM_BLUE
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:10px;")
        lay.addWidget(dot)
        name = QLabel(member.get("nickname", ""))
        name.setStyleSheet(f"color:{C_TEXT}; font-size:12px;")
        lay.addWidget(name)
        tags = []
        if member.get("is_host"):
            tags.append(("房主", C_ACCENT))
        if member.get("is_bot"):
            tags.append(("BOT", C_MUTED))
        if member.get("in_game"):
            tags.append(("对战中", C_OK))
        for text, col in tags:
            tag = QLabel(text)
            tag.setStyleSheet(f"color:{col}; border:1px solid {col}; border-radius:4px;"
                              f"padding:0 4px; font-size:9px;")
            lay.addWidget(tag)
        lay.addStretch(1)


class RoomLobbyWindow(FramelessMixin, QWidget):
    """房间大厅：成员列表、对局信息、房主控制台"""

    def __init__(self, nickname, role, server=None, client=None, callbacks=None, room_info=None):
        super().__init__()
        self.nickname = nickname
        self.role = role  # "host" / "guest"
        self.server = server
        self.client = client
        self.callbacks = callbacks or {}
        self.room_info = room_info or {}
        self.game_running = False
        self._game_started_at = 0.0
        self._closed = False

        self.setWindowTitle("房间大厅")
        self.setFixedSize(1100, 716)
        self.init_frameless(16)
        self._build()
        self._center()

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_events)
        self._poll.start(120)
        self._refresh_members()
        self._refresh_room()

    # ---------- 界面 ----------

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.side = LobbySidePanel()
        self.side.update_info(role="房主" if self.role == "host" else "成员")
        root.addWidget(self.side)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        root.addLayout(right, 1)

        top = QHBoxLayout()
        top.setContentsMargins(24, 12, 12, 4)
        self.lbl_head = QLabel("房 间 大 厅")
        self.lbl_head.setStyleSheet(f"color:{C_MUTED}; font-size:11px; letter-spacing:2px;")
        top.addWidget(self.lbl_head)
        top.addStretch(1)
        self.lbl_addr = QLabel("")
        self.lbl_addr.setStyleSheet(f"color:{C_MUTED}; font-family:{FONT_FAMILY_MONO}; font-size:11px;")
        top.addWidget(self.lbl_addr)
        top.addSpacing(10)
        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("WindowBtn")
        self.btn_min.setFixedSize(30, 26)
        self.btn_min.setStyleSheet(f"QPushButton#WindowBtn{{background:transparent;border:none;color:{C_MUTED};}}"
                                   f"QPushButton#WindowBtn:hover{{background:#1A2330;color:{C_TEXT};border-radius:6px;}}")
        self.btn_min.clicked.connect(self.showMinimized)
        top.addWidget(self.btn_min)
        right.addLayout(top)

        content = QVBoxLayout()
        content.setContentsMargins(22, 6, 24, 6)
        content.setSpacing(10)
        right.addLayout(content, 1)

        # 成员
        member_card = CardFrame("玩家列表")
        self.lbl_member_hint = QLabel("")
        self.lbl_member_hint.setObjectName("Hint")
        member_card.head.addWidget(self.lbl_member_hint)
        teams = QHBoxLayout()
        teams.setSpacing(10)
        self.col_red = QVBoxLayout()
        self.col_red.setSpacing(2)
        self.col_blue = QVBoxLayout()
        self.col_blue.setSpacing(2)
        for col, text, color in (
            (self.col_red, "红队", C_TEAM_RED),
            (self.col_blue, "蓝队", C_TEAM_BLUE),
        ):
            head = QLabel(text)
            head.setStyleSheet(f"color:{color}; font-size:11px; letter-spacing:1px;")
            col.addWidget(head)
            box = QFrame()
            box.setMinimumHeight(96)
            box.setStyleSheet(f"QFrame{{background:{C_PANEL_2}; border:1px solid {C_BORDER}; border-radius:10px;}}")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(6, 6, 6, 6)
            inner.setSpacing(2)
            col.addWidget(box, 1)
            col.addStretch(0)
            setattr(self, f"box_{'red' if color == C_TEAM_RED else 'blue'}", inner)
        teams.addLayout(self.col_red, 1)
        teams.addLayout(self.col_blue, 1)
        member_card.content.addLayout(teams)
        content.addWidget(member_card, 1)

        # 对局信息
        info_card = CardFrame("对局信息")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        self.lbl_mode = QLabel("—")
        self.lbl_score = QLabel("0 : 0")
        self.lbl_score.setStyleSheet(f"color:{C_TEXT}; font-family:{FONT_FAMILY_MONO}; font-size:20px; font-weight:700;")
        self.lbl_rule = QLabel("—")
        self.lbl_rule.setObjectName("Hint")
        for i, (cap, w) in enumerate((("模式", self.lbl_mode), ("比分", self.lbl_score), ("规则", self.lbl_rule))):
            c = QLabel(cap)
            c.setObjectName("Hint")
            grid.addWidget(c, 0, i * 2)
            grid.addWidget(w, 0, i * 2 + 1)
        grid.setColumnStretch(5, 1)
        info_card.content.addLayout(grid)
        content.addWidget(info_card)

        # 操作 + 控制台
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        act_card = CardFrame("房主操作" if self.role == "host" else "等待")
        if self.role == "host":
            self.btn_start = QPushButton("开 始 游 戏")
            self.btn_start.setObjectName("Primary")
            self.btn_start.setCursor(Qt.PointingHandCursor)
            self.btn_start.setFixedHeight(46)
            self.btn_start.clicked.connect(self._host_start)
            act_card.content.addWidget(self.btn_start)

            row = QHBoxLayout()
            row.setSpacing(8)
            self.btn_lock = QPushButton("锁定房间")
            self.btn_lock.setObjectName("Ghost")
            self.btn_lock.setCursor(Qt.PointingHandCursor)
            self.btn_lock.clicked.connect(self._toggle_lock)
            row.addWidget(self.btn_lock)
            self.btn_pwd = QPushButton("设置密码")
            self.btn_pwd.setObjectName("Ghost")
            self.btn_pwd.setCursor(Qt.PointingHandCursor)
            self.btn_pwd.clicked.connect(self._change_pwd)
            row.addWidget(self.btn_pwd)
            row.addStretch(1)
            act_card.content.addLayout(row)

            self.btn_console = QPushButton("打开控制台")
            self.btn_console.setObjectName("Ghost")
            self.btn_console.setCursor(Qt.PointingHandCursor)
            self.btn_console.clicked.connect(self._toggle_console)
            act_card.content.addWidget(self.btn_console)
            act_card.content.addStretch(1)
        else:
            self.lbl_wait = QLabel("等待房主开始游戏…")
            self.lbl_wait.setStyleSheet(f"color:{C_WARN}; font-size:13px;")
            act_card.content.addWidget(self.lbl_wait)
            self.lbl_wait_sub = QLabel("房主开始后会自动启动游戏，请勿关闭大厅")
            self.lbl_wait_sub.setObjectName("Hint")
            self.lbl_wait_sub.setWordWrap(True)
            act_card.content.addWidget(self.lbl_wait_sub)
            act_card.content.addStretch(1)
        bottom.addWidget(act_card, 1)

        self.console_card = CardFrame("控制台（仅房主）")
        self.console_box = QTextEdit()
        self.console_box.setObjectName("ConsoleBox")
        self.console_box.setReadOnly(True)
        self.console_box.setFont(QFont(FONT_FAMILY_MONO, 9))
        self.console_box.setMinimumHeight(150)
        self.console_card.content.addWidget(self.console_box, 1)
        self.console_input = QLineEdit()
        self.console_input.setPlaceholderText("输入命令，例如 status / score set red 5 blue 3 / god all（help 查看全部）")
        self.console_input.returnPressed.connect(self._run_command)
        self.console_card.content.addWidget(self.console_input)
        self.console_card.setVisible(False)
        bottom.addWidget(self.console_card, 1)
        content.addLayout(bottom, 1)

        # 底栏
        bar = QHBoxLayout()
        bar.setContentsMargins(24, 10, 28, 22)
        bar.setSpacing(12)
        self.lbl_status = QLabel("已进入房间")
        self.lbl_status.setStyleSheet(f"color:{C_TEXT}; font-size:12px;")
        bar.addWidget(self.lbl_status)
        bar.addStretch(1)
        self.btn_leave = QPushButton("离开房间")
        self.btn_leave.setObjectName("Danger")
        self.btn_leave.setCursor(Qt.PointingHandCursor)
        self.btn_leave.setFixedHeight(34)
        self.btn_leave.clicked.connect(self.leave_room)
        bar.addWidget(self.btn_leave)
        right.addLayout(bar)

    def _center(self):
        geo = self.frameGeometry()
        geo.moveCenter(self.screen().availableGeometry().center())
        self.move(geo.topLeft())

    # ---------- 数据刷新 ----------

    def _refresh_members(self):
        members = self.server.member_list() if self.server else (self.client.members if self.client else [])
        for box_name in ("box_red", "box_blue"):
            box = getattr(self, box_name)
            while box.count():
                item = box.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
        colors = {"red": 0, "blue": 0}
        for m in members:
            team = m.get("team", "red")
            colors[team if team in colors else "red"] += 1
            box = self.box_red if team == "red" else self.box_blue
            box.addWidget(MemberRow(m))
        for box_name, team in (("box_red", "red"), ("box_blue", "blue")):
            box = getattr(self, box_name)
            if colors[team] == 0:
                empty = QLabel("暂无玩家")
                empty.setStyleSheet(f"color:{C_MUTED}; font-size:11px;")
                box.addWidget(empty)
            box.addStretch(1)

        humans = sum(1 for m in members if not m.get("is_bot"))
        self.side.update_info(
            count=f"{humans} / {self._max_players()}",
            state=self.side.state_text,
        )
        if self.role == "host" and hasattr(self, "btn_start"):
            self.btn_start.setEnabled(humans >= 2 and not self.game_running)

    def _max_players(self):
        room = self._room()
        return room.get("max_players", 2)

    def _room(self):
        if self.server:
            return self.server.room
        if self.client and self.client.room:
            return self.client.room
        return self.room_info

    def _refresh_room(self):
        room = self._room()
        if not room:
            return
        self.side.update_info(
            name=room.get("name", "房间"),
            mode=room.get("mode_label", ""),
            count=f"{room.get('players', 1)} / {room.get('max_players', 2)}",
        )
        self.lbl_mode.setText(room.get("mode_label", ""))
        score = room.get("score", {})
        self.lbl_score.setText(f"{score.get('red', 0)} : {score.get('blue', 0)}")
        target = room.get("score_target", 0)
        limit = room.get("time_limit", 0)
        rule = f"目标 {target} 分 · {limit // 60} 分钟" if target else \
               (f"不限分 · {limit // 60} 分钟" if limit else "不限分 · 不限时")
        self.lbl_rule.setText(rule)
        if self.role == "host":
            self.btn_lock.setText("解锁房间" if room.get("locked") else "锁定房间")
            self.btn_pwd.setText("修改密码" if room.get("has_pwd") or room.get("password") else "设置密码")
            addr = f"本机 25250 · {rn.local_ip()}"
        else:
            addr = f"房主 {room.get('ip', '')}:25250"
        self.lbl_addr.setText(addr)

    # ---------- 事件轮询 ----------

    def _poll_events(self):
        if self._closed:
            return
        source = self.server.events if self.server else (self.client.events if self.client else None)
        if source is None:
            return
        for _ in range(30):
            try:
                kind, payload = source.get_nowait()
            except Exception:  # noqa: BLE001 - queue.Empty
                break
            if kind == "members" or kind in ("member_joined", "member_left"):
                self._refresh_members()
                self._refresh_room()
            elif kind in ("started", "room_update"):
                self._refresh_room()
                self._refresh_members()
            elif kind == "console":
                self._log_console(payload)
            elif kind == "cmd_apply":
                self._log_console(f"[下发] {json.dumps(payload, ensure_ascii=False)}")
            elif kind == "game_started":
                self._on_game_started(payload)
            elif kind == "game_ended":
                self._on_game_ended(payload)
            elif kind == "start":
                self._guest_start_game(payload)
            elif kind == "lobby":
                self._on_game_ended(payload)
            elif kind == "kicked":
                self._fatal(f"你已被移出房间：{payload}")
            elif kind == "closed":
                self._fatal(f"房间已关闭：{payload}")
            elif kind == "disconnected":
                if not self._closed and not self.game_running:
                    self._fatal("与房主的连接已断开")
            elif kind == "error":
                self.lbl_status.setText(f"错误：{payload}")

    def _log_console(self, text):
        if not text:
            return
        stamp = time.strftime("%H:%M:%S")
        self.console_box.append(f"<span style='color:#6B7A90'>[{stamp}]</span> {text}")
        sb = self.console_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------- 房主操作 ----------

    def _host_start(self):
        if not self.server:
            return
        if not self.callbacks.get("python_ready", lambda: True)():
            QMessageBox.warning(self, "无法开始", "运行环境不可用，请返回主界面点“修复环境”。")
            return
        game, err = self.server.start_game()
        if err:
            self.lbl_status.setText(err)
            return
        self._refresh_room()

    def _on_game_started(self, game):
        self.game_running = True
        self._game_started_at = time.time()
        self.side.update_info(state="对战中")
        self.lbl_status.setText("对局进行中 · 已启动游戏进程")
        if hasattr(self, "btn_start"):
            self.btn_start.setEnabled(False)
        member = self.server.host_member if self.server else {}
        args = rn.build_game_args(self.nickname, member.get("team", "red"),
                                  member.get("token", ""), game, True)
        self._launch(args)

    def _launch(self, args):
        launcher = self.callbacks.get("launch_game")
        if not launcher:
            self.lbl_status.setText("缺少游戏启动回调")
            return
        ok = launcher(args, "online", self._on_local_game_finished)
        if not ok:
            self.lbl_status.setText("游戏启动失败")

    def _on_local_game_finished(self, code, status):
        self.game_running = False
        self.side.update_info(state="等待玩家")
        self.lbl_status.setText(f"游戏已退出（{code}），回到大厅")
        if self.server:
            self.server.end_game("对局结束")
        else:
            # 加入方：等房主广播 lobby，超时则自行回大厅
            QTimer.singleShot(2500, lambda: self.side.update_info(state="等待玩家"))

    def _on_game_ended(self, reason):
        self.game_running = False
        self.side.update_info(state="等待玩家")
        self.lbl_status.setText(f"对局结束：{reason}，可再次开始")
        if self.role == "host" and hasattr(self, "btn_start"):
            humans = sum(1 for m in self.server.member_list() if not m["is_bot"]) if self.server else 0
            self.btn_start.setEnabled(humans >= 2)

    def _guest_start_game(self, game):
        if self.game_running:
            return
        self.game_running = True
        self._game_started_at = time.time()
        self.side.update_info(state="对战中")
        self.lbl_status.setText("房主已开始对局，正在启动游戏…")
        me_id = (self.client.you or {}).get("id")
        me = next((p for p in game.get("players", []) if p.get("id") == me_id), None)
        team = (me or {}).get("team", "red")
        token = (me or {}).get("token", "")
        args = rn.build_game_args(self.nickname, team, token, game, False)
        self._launch(args)

    def _toggle_lock(self):
        if not self.server:
            return
        self.server.set_locked(not self.server.room.get("locked"))
        self._refresh_room()

    def _change_pwd(self):
        if not self.server:
            return
        dlg = PasswordDialog(
            "房间", self,
            hint="设置新密码；留空并确定即取消密码。修改后新加入的玩家需要密码。",
            echo=QLineEdit.Normal,
        )
        dlg.edit.setText(self.server.room.get("password", ""))
        if dlg.exec() != QDialog.Accepted:
            return
        self.server.set_password(dlg.password)
        self._refresh_room()
        self._log_console("[系统] 房间密码已更新")

    def _toggle_console(self):
        visible = not self.console_card.isVisible()
        self.console_card.setVisible(visible)
        self.btn_console.setText("收起控制台" if visible else "打开控制台")
        if visible:
            self.console_input.setFocus()
            if not self.console_box.toPlainText():
                self._log_console("[系统] 控制台就绪，输入 help 查看命令")

    def _run_command(self):
        text = self.console_input.text().strip()
        if not text or not self.server:
            return
        self.console_input.clear()
        self._log_console(f"<span style='color:{C_ACCENT}'>房主&gt;</span> {text}")
        ok, reply = self.server.execute_command(text)
        if reply:
            color = C_TEXT if ok else C_BAD
            self._log_console(f"<span style='color:{color}'>{reply.replace(chr(10), '<br>')}</span>")
        self._refresh_room()
        self._refresh_members()

    # ---------- 离开 ----------

    def _fatal(self, message):
        if self._closed:
            return
        self._closed = True
        QMessageBox.information(self, "房间已结束", message)
        self._finish_leave()

    def leave_room(self):
        if self._closed:
            return
        if self.role == "host" and self.game_running:
            ret = QMessageBox.question(self, "退出房间", "对局进行中，确定解散房间？")
            if ret != QMessageBox.Yes:
                return
        self._closed = True
        self._finish_leave()

    def _finish_leave(self):
        self._poll.stop()
        try:
            if self.server:
                self.server.stop("房主已离开，房间解散")
            if self.client:
                self.client.leave()
        except Exception:  # noqa: BLE001
            pass
        cb = self.callbacks.get("on_leave")
        self.close()
        if cb:
            cb()

    def closeEvent(self, event):  # noqa: N802
        if not self._closed:
            self._closed = True
            self._poll.stop()
            if self.server:
                self.server.stop("房主已离开，房间解散")
            if self.client:
                self.client.leave()
            cb = self.callbacks.get("on_leave")
            if cb:
                QTimer.singleShot(0, cb)
        super().closeEvent(event)
