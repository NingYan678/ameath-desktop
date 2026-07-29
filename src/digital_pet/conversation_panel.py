"""Adaptive conversation UI for the Hermes-native desktop channel."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeyEvent, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .markdown_renderer import is_safe_link, markdown_to_plain, render_markdown
from .preferences import DesktopPreferences


@dataclass
class ConversationMessage:
    role: str
    content: str
    draft: bool = False


class ChatComposer(QTextEdit):
    """Enter sends; Shift+Enter keeps a readable multi-line draft."""

    submitted = Signal(str)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and not event.modifiers() & Qt.ShiftModifier:
            text = self.toPlainText().strip()
            if text:
                self.submitted.emit(text)
            event.accept()
            return
        super().keyPressEvent(event)


class ClickableFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AmeathAvatar(QWidget):
    """Small, unobtrusive identity mark used in the glass-window title bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(2, 1, 26, 27)
        gradient.setColorAt(0, QColor("#ffd3e5"))
        gradient.setColorAt(0.5, QColor("#e9a8d0"))
        gradient.setColorAt(1, QColor("#9ee9f5"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(1, 1, 26, 26)
        painter.setPen(QColor("#463650"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, "A")
        painter.end()


class IconButton(QPushButton):
    """A compact, font-independent action button with an accessible text name."""

    def __init__(self, icon: str, label: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._icon = icon
        self.setText("")
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#56365c") if self.objectName() == "sendButton" else QColor("#fff9fd")
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        box = self.rect().adjusted(8, 8, -8, -8)
        left, top, right, bottom = box.left(), box.top(), box.right(), box.bottom()
        middle_x, middle_y = box.center().x(), box.center().y()
        if self._icon == "expand":
            painter.drawLine(left, top + 2, middle_x, bottom - 2)
            painter.drawLine(middle_x, bottom - 2, right, top + 2)
        elif self._icon == "collapse":
            painter.drawLine(left, bottom - 2, middle_x, top + 2)
            painter.drawLine(middle_x, top + 2, right, bottom - 2)
        elif self._icon == "settings":
            painter.drawEllipse(box.adjusted(3, 3, -3, -3))
            painter.drawLine(middle_x, top, middle_x, top + 3)
            painter.drawLine(middle_x, bottom - 3, middle_x, bottom)
            painter.drawLine(left, middle_y, left + 3, middle_y)
            painter.drawLine(right - 3, middle_y, right, middle_y)
        elif self._icon == "send":
            painter.drawLine(left, middle_y, right, top)
            painter.drawLine(right, top, right - 4, bottom)
            painter.drawLine(right - 4, bottom, left, middle_y)
            painter.drawLine(left + 2, middle_y, middle_x + 1, middle_y + 1)
            painter.drawLine(middle_x + 1, middle_y + 1, right - 3, top + 2)
        painter.end()


class ConversationPanel(QWidget):
    """One-pair compact bubble and a ten-message continuous conversation panel."""

    message_submitted = Signal(str)
    expanded_changed = Signal(bool)
    activity = Signal()
    layout_changed = Signal()
    action_confirmed = Signal()
    action_cancelled = Signal()
    settings_requested = Signal()
    proactive_response_requested = Signal()

    MAX_MESSAGES = 10
    COMPACT_WIDTH = 360
    EXPANDED_WIDTH = 520
    COMPACT_HEIGHT = 116
    EXPANDED_HEIGHT = 408

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._messages: list[ConversationMessage] = []
        self._expanded = False
        self._streaming = False
        self._draft_browser: QTextBrowser | None = None
        self._draft_render_timer = QTimer(self)
        self._draft_render_timer.setSingleShot(True)
        self._draft_render_timer.setInterval(80)
        self._draft_render_timer.timeout.connect(self._flush_draft_render)
        self._status_text = "正在连接 Hermes Gateway…"
        self._proactive_prompt = ""
        self._compact_width = self.COMPACT_WIDTH
        self._expanded_width = self.EXPANDED_WIDTH
        self._compact_height = self.COMPACT_HEIGHT
        self._expanded_height = self.EXPANDED_HEIGHT
        self._base_style = ""
        self.setAttribute(Qt.WA_TranslucentBackground)
        # A transparent top-level window does not always paint a child widget's
        # stylesheet background on Windows.  This makes the panel itself the
        # styled surface, so its opacity remains visible at every setting.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._build_ui()
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.setGraphicsEffect(shadow)
        self._render()
        self._watch_activity(self)

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def messages(self) -> tuple[ConversationMessage, ...]:
        return tuple(self._messages)

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def has_pending_action(self) -> bool:
        return not self.action_bar.isHidden()

    @property
    def has_unsent_text(self) -> bool:
        return bool(self.composer.toPlainText().strip())

    def panel_size(self, maximum_width: int) -> QSize:
        desired_width = self._expanded_width if self._expanded else self._compact_width
        return QSize(min(desired_width, maximum_width), self._expanded_height if self._expanded else self._compact_height)

    def apply_preferences(self, preferences: DesktopPreferences) -> None:
        self._compact_width = preferences.compact_width
        self._expanded_width = max(preferences.expanded_width, preferences.compact_width)
        self._expanded_height = preferences.expanded_height
        opacity = max(20, min(100, preferences.panel_opacity)) / 100
        # Do not only vary the outer gradient: the message cards and composer
        # cover much of the panel, which made the old control appear inert.
        # These values deliberately span a visible glass-to-solid range.
        # The expanded panel has its own surface.  Both the outer shell and
        # the continuous-chat surface must reach 255 at 100%, otherwise the
        # setting feels different between compact and expanded states.
        root_alpha = round(32 + 223 * opacity)
        expanded_alpha = round(20 + 235 * opacity)
        # Message surfaces retain a readable frosted layer even at 20%.
        # The slider controls the ambient panel glass; it must not make a
        # reply disappear against an arbitrary desktop wallpaper.
        card_alpha = round(108 + 90 * opacity)
        incoming_alpha = round(118 + 82 * opacity)
        outgoing_alpha = round(150 + 78 * opacity)
        action_alpha = round(95 + 70 * opacity)
        control_alpha = round(50 + 65 * opacity)
        composer_alpha = round(115 + 80 * opacity)
        border_alpha = round(55 + 105 * opacity)
        scale = preferences.font_scale / 100
        self.setStyleSheet(
            self._base_style
            # Qt's translucent gradient rendering is inconsistent on some
            # Windows setups.  A plain tinted glass surface is predictable and
            # lets the desktop visibly show through at low opacity.
            + f"QWidget#conversationPanel {{ background: rgba(66, 51, 87, {root_alpha}); border: 1px solid rgba(255, 233, 248, {border_alpha}); border-radius: 20px; }}"
            + f"QFrame#expandedFrame {{ background: rgba(58, 44, 79, {expanded_alpha}); border: 1px solid rgba(255, 233, 248, {max(38, border_alpha - 24)}); border-radius: 15px; }}"
            + f"QFrame#compactCard {{ background: rgba(47, 37, 69, {card_alpha}); border-color: rgba(255, 239, 249, {max(38, border_alpha - 48)}); }}"
            + f"QFrame#messageIncoming {{ background: rgba(52, 43, 78, {incoming_alpha}); border-color: rgba(255, 242, 251, {max(32, border_alpha - 58)}); }}"
            + f"QFrame#messageOutgoing {{ background: rgba(126, 112, 194, {outgoing_alpha}); border-color: rgba(219, 225, 255, {max(48, border_alpha - 35)}); }}"
            + f"QFrame#actionBar {{ background: rgba(255, 220, 137, {action_alpha}); border-color: rgba(255, 237, 178, {max(42, border_alpha - 18)}); }}"
            + f"QPushButton#iconButton, QPushButton#secondaryButton {{ background: rgba(255, 236, 248, {control_alpha}); border-color: rgba(255, 242, 250, {max(38, border_alpha - 48)}); }}"
            + f"QTextEdit#composer {{ background: rgba(50, 38, 66, {composer_alpha}); border-color: rgba(255, 236, 248, {max(40, border_alpha - 44)}); }}"
            + f"QTextEdit#composer:focus {{ background: rgba(54, 41, 73, {min(255, composer_alpha + 28)}); border-color: rgba(165, 232, 246, {min(255, border_alpha + 25)}); }}"
            + f"QWidget#conversationPanel QLabel {{ font-size: {max(9, round(12 * scale))}px; }}"
        )
        self._render()

    def expand(self, *, focus_input: bool = False) -> None:
        if not self._expanded:
            self._expanded = True
            self._render()
            self.expanded_changed.emit(True)
        self.activity.emit()
        if focus_input:
            self.composer.setFocus()

    def collapse(self, *, force: bool = False) -> bool:
        if not self._expanded or (not force and not self.can_auto_collapse()):
            return False
        self._expanded = False
        self._render()
        self.expanded_changed.emit(False)
        return True

    def can_auto_collapse(self) -> bool:
        return self._expanded and not self._streaming and not self.has_pending_action and not self.has_unsent_text and not self.underMouse()

    def add_user_message(self, content: str) -> None:
        self._append("user", content)
        self.expand()

    def update_assistant_draft(self, content: str) -> None:
        content = content.strip()
        if not content:
            return
        # A streamed answer is the new visible conversation state.  Clear the
        # transient "message handed to Hermes" label so the compact preview
        # cannot keep showing that older status once the draft arrives.
        self._status_text = ""
        self._streaming = True
        if self._messages and self._messages[-1].role == "assistant" and self._messages[-1].draft:
            self._messages[-1].content = content
        else:
            self._append("assistant", content, draft=True, render=False)
            if self._expanded:
                self._render_messages()
        self.expand()
        self._draft_render_timer.start()
        self.activity.emit()

    def finalize_assistant(self, content: str) -> None:
        content = content.strip()
        self._streaming = False
        self._draft_render_timer.stop()
        # Once Hermes has answered, the answer itself becomes the compact
        # preview.  Later proactive/status bubbles can then replace it through
        # show_status() and remain visible after the chat collapses.
        self._status_text = ""
        if not content:
            self._render()
            return
        if self._messages and self._messages[-1].role == "assistant" and self._messages[-1].draft:
            self._messages[-1].content = content
            self._messages[-1].draft = False
            self._flush_draft_render()
        else:
            self._append("assistant", content, render=False)
            self._render_messages()
        self.expand()
        self.activity.emit()

    def show_status(self, text: str, *, expand: bool = False) -> None:
        self._status_text = text.strip()
        if expand:
            self.expand()
        self._render_status()

    def show_proactive_prompt(self, question: str) -> None:
        self._proactive_prompt = question.strip()
        self.respond_button.setVisible(bool(self._proactive_prompt) and not self._expanded)
        self._render_status()

    def clear_proactive_prompt(self) -> None:
        self._proactive_prompt = ""
        self.respond_button.hide()
        self.composer.setPlaceholderText("和爱弥斯说点什么…（Enter 发送，Shift+Enter 换行）")

    def begin_proactive_reply(self) -> None:
        if not self._proactive_prompt:
            return
        prompt = self._proactive_prompt.replace("\n", " ").strip()
        self.composer.setPlaceholderText(f"回应：{prompt[:48]}")
        self.respond_button.hide()
        self.expand(focus_input=True)

    def show_action(self, question: str, primary_label: str, cancel_label: str) -> None:
        self._streaming = False
        self._status_text = "Hermes 需要你的确认"
        self.action_question.setText(question)
        self.confirm_button.setText(primary_label)
        self.cancel_button.setText(cancel_label)
        self.action_bar.show()
        self.expand()
        self._render()

    def clear_action(self) -> None:
        self.action_bar.hide()
        self._render()
        self.activity.emit()

    def clear_composer(self) -> None:
        self.composer.clear()

    def _append(self, role: str, content: str, *, draft: bool = False, render: bool = True) -> None:
        self._messages.append(ConversationMessage(role=role, content=content.strip(), draft=draft))
        self._messages = self._messages[-self.MAX_MESSAGES :]
        if render:
            self._render_messages()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "QWidget#conversationPanel { background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 rgba(84, 53, 86, 150), stop: 0.48 rgba(57, 47, 83, 142), stop: 1 rgba(43, 67, 91, 148)); border: 1px solid rgba(255, 233, 248, 112); border-radius: 20px; }"
            "QLabel { color: #fff9fd; border: none; }"
            "QLabel#secondaryLabel { color: rgba(255, 229, 244, 178); }"
            "QLabel#statusLabel { color: rgba(232, 246, 255, 198); font-size: 11px; }"
            "QFrame#expandedFrame, QScrollArea#historyArea, QWidget#historyHost { background: transparent; border: none; }"
            "QFrame#compactCard { background: rgba(255, 228, 244, 34); border: 1px solid rgba(255, 239, 249, 64); border-radius: 14px; }"
            "QFrame#messageIncoming { background: rgba(255, 242, 250, 42); border: 1px solid rgba(255, 242, 251, 54); border-radius: 14px; }"
            "QFrame#messageOutgoing { background: rgba(126, 112, 194, 174); border: 1px solid rgba(219, 225, 255, 95); border-radius: 14px; }"
            "QFrame#actionBar { background: rgba(255, 220, 137, 48); border: 1px solid rgba(255, 237, 178, 108); border-radius: 12px; }"
            "QPushButton#iconButton { background: rgba(255, 236, 248, 40); color: #fff9fd; border: 1px solid rgba(255, 242, 250, 72); border-radius: 12px; padding: 2px 8px; }"
            "QPushButton#iconButton:hover { background: rgba(255, 236, 248, 73); }"
            "QPushButton#secondaryButton { background: rgba(255, 238, 248, 31); color: #fff9fd; border: 1px solid rgba(255, 242, 250, 68); border-radius: 9px; padding: 4px 10px; }"
            "QPushButton#primaryButton { background: #ffe2f0; color: #4d3657; border: none; border-radius: 9px; padding: 4px 11px; font-weight: 600; }"
            "QPushButton#sendButton { background: #ffe1ef; color: #56365c; border: 1px solid rgba(255, 255, 255, 120); border-radius: 17px; }"
            "QPushButton#sendButton:hover { background: #fff0f7; }"
            "QTextEdit#composer { background: rgba(50, 38, 66, 74); color: #fff9fd; border: 1px solid rgba(255, 236, 248, 68); border-radius: 15px; padding: 7px 10px; }"
            "QTextEdit#composer:focus { border: 1px solid rgba(165, 232, 246, 178); background: rgba(54, 41, 73, 105); }"
            "QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 0; }"
            "QScrollBar::handle:vertical { background: rgba(255, 225, 244, 86); border-radius: 2px; min-height: 22px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.setObjectName("conversationPanel")
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(12, 10, 12, 11)
        self.root_layout.setSpacing(7)
        self._base_style = self.styleSheet()

        self.compact_frame = ClickableFrame(self)
        self.compact_frame.setObjectName("compactCard")
        compact_layout = QVBoxLayout(self.compact_frame)
        compact_layout.setContentsMargins(12, 9, 9, 9)
        compact_layout.setSpacing(3)
        compact_header = QHBoxLayout()
        compact_avatar = AmeathAvatar(self.compact_frame)
        compact_title = QLabel("爱弥斯", self.compact_frame)
        compact_title.setStyleSheet("font-weight: 650;")
        compact_subtitle = QLabel("✦ Hermes · 本地管家", self.compact_frame)
        compact_subtitle.setObjectName("secondaryLabel")
        compact_subtitle.setStyleSheet("font-size: 10px;")
        self.expand_button = IconButton("expand", "展开对话", self.compact_frame)
        self.expand_button.setObjectName("iconButton")
        self.expand_button.setFixedSize(30, 30)
        self.respond_button = QPushButton("回应", self.compact_frame)
        self.respond_button.setObjectName("primaryButton")
        self.respond_button.setAccessibleDescription("Proactive reply opens the conversation and keeps Ameath's question in context.")
        self.respond_button.setAccessibleName("回应爱弥斯的主动提问")
        self.respond_button.setToolTip("回应爱弥斯刚才的问题")
        self.respond_button.setFixedHeight(26)
        self.respond_button.hide()
        compact_header.addWidget(compact_avatar)
        compact_header.addWidget(compact_title)
        compact_header.addWidget(compact_subtitle)
        compact_header.addStretch(1)
        compact_header.addWidget(self.respond_button)
        compact_header.addWidget(self.expand_button)
        self.compact_user = QLabel(self.compact_frame)
        self.compact_assistant = QLabel(self.compact_frame)
        for label in (self.compact_user, self.compact_assistant):
            label.setWordWrap(False)
            label.setTextFormat(Qt.PlainText)
        self.compact_user.setObjectName("secondaryLabel")
        self.compact_user.setStyleSheet("font-size: 10px;")
        self.compact_assistant.setStyleSheet("font-weight: 550; font-size: 12px;")
        compact_layout.addLayout(compact_header)
        compact_layout.addWidget(self.compact_user)
        compact_layout.addWidget(self.compact_assistant)
        self.root_layout.addWidget(self.compact_frame)
        self.expand_button.clicked.connect(self.expand)
        self.respond_button.clicked.connect(self.proactive_response_requested.emit)
        self.compact_frame.clicked.connect(self.expand)

        self.expanded_frame = QFrame(self)
        self.expanded_frame.setObjectName("expandedFrame")
        expanded_layout = QVBoxLayout(self.expanded_frame)
        expanded_layout.setContentsMargins(2, 0, 2, 0)
        expanded_layout.setSpacing(6)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(7)
        avatar = AmeathAvatar(self.expanded_frame)
        title = QLabel("爱弥斯", self.expanded_frame)
        title.setStyleSheet("font-size: 13px; font-weight: 700;")
        subtitle = QLabel("✦ Hermes · 桌面终端", self.expanded_frame)
        subtitle.setObjectName("secondaryLabel")
        subtitle.setStyleSheet("font-size: 10px;")
        title_stack = QVBoxLayout()
        title_stack.setSpacing(0)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        self.collapse_button = IconButton("collapse", "收起对话", self.expanded_frame)
        self.collapse_button.setObjectName("iconButton")
        self.collapse_button.setFixedSize(30, 30)
        self.settings_button = IconButton("settings", "设置", self.expanded_frame)
        self.settings_button.setObjectName("iconButton")
        self.settings_button.setFixedSize(30, 30)
        header_layout.addWidget(avatar)
        header_layout.addLayout(title_stack)
        header_layout.addStretch(1)
        header_layout.addWidget(self.settings_button)
        header_layout.addWidget(self.collapse_button)
        expanded_layout.addLayout(header_layout)
        self.status_label = QLabel(self.expanded_frame)
        self.status_label.setObjectName("statusLabel")
        expanded_layout.addWidget(self.status_label)

        self.history = QScrollArea(self.expanded_frame)
        self.history.setObjectName("historyArea")
        self.history.setWidgetResizable(True)
        self.history.setFrameShape(QFrame.NoFrame)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_host = QWidget(self.history)
        self.history_host.setObjectName("historyHost")
        self.history_host.setAttribute(Qt.WA_TranslucentBackground)
        self.history.viewport().setAttribute(Qt.WA_TranslucentBackground)
        self.history_layout = QVBoxLayout(self.history_host)
        self.history_layout.setContentsMargins(2, 2, 2, 2)
        self.history_layout.setSpacing(6)
        self.history_layout.addStretch(1)
        self.history.setWidget(self.history_host)
        expanded_layout.addWidget(self.history, 1)

        self.action_bar = QFrame(self.expanded_frame)
        self.action_bar.setObjectName("actionBar")
        action_layout = QVBoxLayout(self.action_bar)
        action_layout.setContentsMargins(7, 5, 7, 5)
        action_layout.setSpacing(4)
        self.action_question = QLabel(self.action_bar)
        self.action_question.setWordWrap(True)
        self.action_question.setStyleSheet("color: #fff0b9; font-size: 11px;")
        action_buttons = QHBoxLayout()
        self.confirm_button = QPushButton("批准", self.action_bar)
        self.cancel_button = QPushButton("拒绝", self.action_bar)
        self.confirm_button.setObjectName("primaryButton")
        self.cancel_button.setObjectName("secondaryButton")
        self.confirm_button.setAccessibleName("Confirm Hermes action")
        self.cancel_button.setAccessibleName("Cancel Hermes action")
        action_buttons.addStretch(1)
        action_buttons.addWidget(self.cancel_button)
        action_buttons.addWidget(self.confirm_button)
        action_layout.addWidget(self.action_question)
        action_layout.addLayout(action_buttons)
        self.action_bar.hide()
        self.confirm_button.clicked.connect(lambda: self.action_confirmed.emit())
        self.cancel_button.clicked.connect(lambda: self.action_cancelled.emit())
        expanded_layout.addWidget(self.action_bar)

        composer_layout = QHBoxLayout()
        self.composer = ChatComposer(self.expanded_frame)
        self.composer.setObjectName("composer")
        self.composer.setAccessibleName("Message to Hermes")
        self.composer.setPlaceholderText("和爱弥斯说点什么…（Enter 发送，Shift+Enter 换行）")
        self.composer.setFixedHeight(50)
        self.send_button = IconButton("send", "发送消息", self.expanded_frame)
        self.send_button.setObjectName("sendButton")
        self.send_button.setFixedSize(36, 36)
        composer_layout.addWidget(self.composer, 1)
        composer_layout.addWidget(self.send_button)
        expanded_layout.addLayout(composer_layout)
        self.root_layout.addWidget(self.expanded_frame)
        self.collapse_button.clicked.connect(lambda: self.collapse(force=True))
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.composer.submitted.connect(self._submit_composer)
        self.send_button.clicked.connect(self._submit_composer)
        self.composer.textChanged.connect(self.activity)

        self._watch_activity(self.history.viewport())
        self._watch_activity(self.composer)
        self._watch_activity(self.send_button)
        self._watch_activity(self.expand_button)
        self._watch_activity(self.respond_button)
        self._watch_activity(self.collapse_button)
        self._watch_activity(self.confirm_button)
        self._watch_activity(self.cancel_button)

    def _submit_composer(self, text: str | bool = False) -> None:
        message = text if isinstance(text, str) else self.composer.toPlainText().strip()
        if not message.strip():
            return
        self.clear_composer()
        self.clear_proactive_prompt()
        self.message_submitted.emit(message.strip())
        self.activity.emit()

    def _render(self) -> None:
        self.compact_frame.setVisible(not self._expanded)
        self.expanded_frame.setVisible(self._expanded)
        self._render_messages()
        self._render_status()
        self.setFixedHeight(self._expanded_height if self._expanded else self._compact_height)
        self.layout_changed.emit()

    def _render_status(self) -> None:
        self.status_label.setText(self._status_text or "已就绪")
        last_user = next((item.content for item in reversed(self._messages) if item.role == "user"), "")
        last_assistant = next((item.content for item in reversed(self._messages) if item.role == "assistant"), self._status_text)
        # A short status/proactive bubble is newer than the last chat message.
        # Prefer it in the compact preview so a collapsed window does not look
        # stuck on an older conversation after the user has chatted.
        preview = self._status_text or last_assistant
        preview = markdown_to_plain(preview)
        self.compact_user.setText(self._elide(f"你：{last_user}") if last_user else "爱弥斯正在待命")
        self.compact_assistant.setText(self._elide(f"爱弥斯：{preview}") if preview else "点击展开连续对话")

    def _render_messages(self) -> None:
        self._draft_browser = None
        while self.history_layout.count() > 1:
            item = self.history_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for message in self._messages:
            self.history_layout.insertWidget(self.history_layout.count() - 1, self._message_card(message))
        self._render_status()
        if self._expanded:
            self.history.verticalScrollBar().setValue(self.history.verticalScrollBar().maximum())

    def _flush_draft_render(self) -> None:
        if self._draft_browser is None or not self._messages:
            return
        message = self._messages[-1]
        if message.role != "assistant":
            return
        self._draft_browser.setHtml(render_markdown(message.content + ("  …" if message.draft else "")))
        frame = self._draft_browser.parentWidget()
        if isinstance(frame, QFrame):
            self._draft_browser.document().setTextWidth(frame.maximumWidth() - 22)
        self._draft_browser.setFixedHeight(max(24, int(self._draft_browser.document().size().height()) + 6))
        self._render_status()
        if self._expanded:
            self.history.verticalScrollBar().setValue(self.history.verticalScrollBar().maximum())

    def _message_card(self, message: ConversationMessage) -> QWidget:
        row = QWidget(self.history_host)
        row.setAttribute(Qt.WA_TranslucentBackground)
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(1, 0, 1, 0)
        frame = QFrame(row)
        frame.setMaximumWidth(372)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(11, 8, 11, 8)
        frame_layout.setSpacing(0)
        if message.role == "assistant":
            content = self._assistant_content(message.content + ("  …" if message.draft else ""), frame)
            if message.draft:
                self._draft_browser = content
        else:
            content = QLabel(message.content, frame)
            content.setWordWrap(True)
            content.setTextFormat(Qt.PlainText)
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        frame_layout.addWidget(content)
        if message.role == "user":
            frame.setObjectName("messageOutgoing")
            layout.addStretch(1)
            layout.addWidget(frame)
        else:
            frame.setObjectName("messageIncoming")
            layout.addWidget(frame)
            layout.addStretch(1)
        return row

    def _assistant_content(self, text: str, frame: QFrame) -> QTextBrowser:
        content = QTextBrowser(frame)
        content.setOpenLinks(False)
        content.setOpenExternalLinks(False)
        content.setFrameShape(QFrame.NoFrame)
        content.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        content.setStyleSheet(
            "QTextBrowser { background: transparent; color: #fff9fd; border: none; padding: 0; }"
            "h1 { font-size: 18px; margin: 3px 0 6px 0; } h2 { font-size: 16px; margin: 3px 0 5px 0; } h3 { font-size: 14px; margin: 2px 0 4px 0; }"
            "p { margin: 0 0 5px 0; } ul, ol { margin: 2px 0 5px 18px; padding: 0; }"
            "blockquote { color: #d7c9ed; border-left: 3px solid #9ee9f5; margin: 3px 0; padding-left: 7px; }"
            "code { font-family: Consolas, 'Courier New', monospace; color: #ffe6b0; background: #302841; }"
            "pre { font-family: Consolas, 'Courier New', monospace; color: #f7eaf2; background: #211b31; padding: 7px; border-radius: 6px; }"
            "a { color: #9ee9f5; text-decoration: underline; }"
        )
        content.setHtml(render_markdown(text))
        content.document().setTextWidth(frame.maximumWidth() - 22)
        content.setFixedHeight(max(24, int(content.document().size().height()) + 6))
        content.anchorClicked.connect(self._open_link)
        return content

    @staticmethod
    def _open_link(url) -> None:  # type: ignore[no-untyped-def]
        if is_safe_link(url.toString()):
            QDesktopServices.openUrl(url)

    def _elide(self, text: str) -> str:
        return self.fontMetrics().elidedText(text.replace("\n", " "), Qt.ElideRight, 320)

    def _watch_activity(self, watched: QObject) -> None:
        watched.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {QEvent.Enter, QEvent.MouseMove, QEvent.Wheel, QEvent.KeyPress, QEvent.FocusIn}:
            self.activity.emit()
        return super().eventFilter(watched, event)
