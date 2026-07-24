from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QMovie, QPainter, QPen
from PySide6.QtWidgets import QInputDialog, QLabel, QMenu, QWidget

from .ameath_runtime import AmeathRuntimeService
from .butler_protocol import BubblePriority, BubbleScheduler
from .config import PROJECT_ROOT, Settings
from .conversation_panel import ConversationPanel
from .hermes_desktop_client import HermesDesktopClient
from .hermes_settings import HermesSettingsService
from .preferences import DesktopPreferences, StartupManager, UISettingsStore
from .settings_dialog import SettingsDialog


ANIMATIONS = {
    "idle_soft": "idle1.gif", "idle_alert": "idle2.gif", "idle_happy": "idle3.gif", "idle_sleepy": "idle4.gif",
    "move": "move.gif", "drag": "drag.gif", "notice": "screen1.gif", "sad": "screen2.gif",
    "attention": "screen3.gif", "thinking": "screen4.gif", "busy": "screen5.gif", "rest": "screen6.gif",
    "question": "screen7.gif", "music": "ameath.gif",
}
ANIMATION_LABELS = {
    "idle_soft": "待机：眨眼", "idle_alert": "待机：注意", "idle_happy": "待机：微笑", "idle_sleepy": "待机：困倦",
    "move": "移动过渡", "drag": "拖动反馈", "notice": "关注你", "sad": "难过", "attention": "回应你",
    "thinking": "思考", "busy": "专注", "rest": "休息", "question": "等待指令", "music": "小小音乐会",
}
IDLE_ANIMATIONS = ("idle_soft", "idle_alert", "idle_happy", "idle_sleepy")
GATEWAY_ANIMATIONS = {
    "thinking": "thinking", "running": "busy", "analyzing": "thinking", "building": "busy",
    "searching": "attention", "permission": "question", "celebrating": "music", "failed": "sad",
    "idle": "idle_soft", "attention": "attention",
}


class NativePulse(QWidget):
    """A small local animation for Hermes-originated notifications."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._advance)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def activate(self, duration_ms: int = 6_000) -> None:
        self._phase = 0
        self.show()
        self.raise_()
        self._timer.start()
        self._hide_timer.start(duration_ms)

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        self._phase = (self._phase + 1) % 20
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        radius = 72 + (self._phase % 10) * 4
        alpha = 185 - (self._phase % 10) * 14
        center = self.rect().center()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(255, 163, 207, max(alpha, 35)), 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)
        accent_pen = QPen(QColor(167, 239, 247, 230), 4)
        accent_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(accent_pen)
        painter.drawLine(center.x(), center.y(), center.x(), center.y() - 25)
        painter.drawLine(center.x(), center.y(), center.x() + 20, center.y() + 8)
        painter.end()


class PetWindow(QWidget):
    PET_SIZE = 200

    def __init__(self, settings: Settings, runtime: AmeathRuntimeService | None = None) -> None:
        super().__init__()
        self.settings = settings
        self._settings_store = UISettingsStore(settings.data_root)
        self.preferences = self._settings_store.load()
        self._startup_manager = StartupManager(settings.launch_command)
        self._runtime = runtime or AmeathRuntimeService(settings)
        self._hermes_settings = HermesSettingsService(
            settings.hermes_home,
            python=settings.hermes_cli_python,
            source=settings.hermes_source,
            restart_handler=self._runtime.restart_gateway,
        )
        self._drag_offset: QPoint | None = None
        self._drag_started = False
        self._movie: QMovie | None = None
        self._bubble_scheduler = BubbleScheduler()
        self._pending_action: dict[str, Any] | None = None
        self._current_animation = "idle_soft"
        self._paused = False
        self._gateway = HermesDesktopClient(settings, self)
        self._gateway.connected.connect(self._on_gateway_connected)
        self._gateway.disconnected.connect(self._on_gateway_disconnected)
        self._gateway.event_received.connect(self._on_gateway_event)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._return_to_idle)
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(9_000)
        self._idle_timer.timeout.connect(self._auto_switch)
        self._rest_timer = QTimer(self)
        self._rest_timer.setSingleShot(True)
        self._rest_timer.timeout.connect(self._rest_after_inactivity)
        self._conversation_timer = QTimer(self)
        self._conversation_timer.setSingleShot(True)
        self._conversation_timer.timeout.connect(self._collapse_conversation_when_idle)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.pet = QLabel(self)
        self.pet.setAlignment(Qt.AlignCenter)
        self.conversation = ConversationPanel(self)
        self.conversation.message_submitted.connect(self._send_chat_message)
        self.conversation.settings_requested.connect(self.open_settings)
        self.conversation.expanded_changed.connect(self._on_conversation_expanded_changed)
        self.conversation.activity.connect(self._on_conversation_activity)
        self.conversation.layout_changed.connect(self._layout_window)
        self.conversation.action_confirmed.connect(self.confirm_pending_action)
        self.conversation.action_cancelled.connect(self.cancel_pending_action)
        self._native_pulse = NativePulse(self)
        self.apply_preferences(self.preferences)
        self._layout_window()
        if not self._load_animation(self._current_animation):
            self.pet.setText("未找到本地角色素材")
            self.pet.setStyleSheet("color: white; background: rgba(20, 30, 48, 160); border-radius: 16px;")
        self._speak("正在连接 Hermes Gateway…", BubblePriority.ACTIVITY)
        self._idle_timer.start()
        self._register_activity()
        self._gateway.start()

    def _asset(self, filename: str) -> Path:
        return self.settings.asset_root / "gifs" / filename

    def _load_animation(self, name: str) -> bool:
        source = self._asset(ANIMATIONS[name])
        if not source.exists():
            return False
        movie = QMovie(str(source), parent=self)
        movie.setScaledSize(QSize(self.preferences.pet_size, self.preferences.pet_size))
        movie.setSpeed(self.preferences.animation_speed)
        if not movie.isValid():
            return False
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
        self._movie = movie
        self.pet.setMovie(movie)
        movie.start()
        self._current_animation = name
        self._paused = False
        return True

    def apply_preferences(self, preferences: DesktopPreferences, *, update_window_flags: bool = True) -> None:
        self.preferences = preferences
        self.conversation.apply_preferences(preferences)
        if self._movie is not None:
            self._movie.setScaledSize(QSize(preferences.pet_size, preferences.pet_size))
            self._movie.setSpeed(preferences.animation_speed)
        if update_window_flags:
            flags = Qt.FramelessWindowHint | Qt.Tool
            if preferences.always_on_top:
                flags |= Qt.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            if self.isVisible():
                self.show()
        self._layout_window()

    def _layout_window(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        max_width = max(280, (screen.availableGeometry().width() - 36) if screen is not None else self.preferences.expanded_width)
        panel_size = self.conversation.panel_size(max_width)
        width, panel_height = panel_size.width(), panel_size.height()
        pet_size = self.preferences.pet_size
        total_height = panel_height + pet_size + 14
        self.setFixedSize(QSize(width, total_height))
        self.conversation.setGeometry(0, 0, width, panel_height)
        pet_left = (width - pet_size) // 2
        pet_top = panel_height + 4
        self.pet.setGeometry(pet_left, pet_top, pet_size, pet_size)
        self._native_pulse.setGeometry(pet_left, pet_top, pet_size, pet_size)

    def _react(self, animation: str, text: str, duration_ms: int = 2_000, *, priority: BubblePriority = BubblePriority.ACTIVITY) -> None:
        self._settle_timer.stop()
        self._load_animation(animation)
        self._speak(text, priority)
        self._settle_timer.start(duration_ms)

    def _speak(self, text: str, priority: BubblePriority = BubblePriority.ACTIVITY) -> None:
        if self._bubble_scheduler.should_show(priority):
            self.conversation.show_status(text)

    def _register_activity(self) -> None:
        self._rest_timer.start(45_000)

    def _on_conversation_activity(self) -> None:
        self._register_activity()
        if self.conversation.is_expanded:
            self._conversation_timer.start(self.preferences.auto_collapse_seconds * 1_000)

    def _on_conversation_expanded_changed(self, expanded: bool) -> None:
        self._layout_window()
        if expanded:
            self._conversation_timer.start(self.preferences.auto_collapse_seconds * 1_000)
        else:
            self._conversation_timer.stop()

    def _collapse_conversation_when_idle(self) -> None:
        if self.conversation.collapse():
            self._layout_window()
        elif self.conversation.is_expanded:
            self._conversation_timer.start(5_000)

    def _return_to_idle(self) -> None:
        if self._drag_offset is None and self._pending_action is None:
            self._load_animation(random.choice(IDLE_ANIMATIONS))

    def _auto_switch(self) -> None:
        if self._paused or self._drag_offset is not None or self._pending_action is not None or self._settle_timer.isActive():
            return
        self._load_animation(random.choice(IDLE_ANIMATIONS))

    def _rest_after_inactivity(self) -> None:
        if self._drag_offset is None and self._pending_action is None and not self._paused:
            self._react("rest", "我会在这里等待 Hermes 的下一条消息。", 4_000)

    def _on_gateway_connected(self) -> None:
        self._react("attention", "已连接到 Hermes。", 1_500, priority=BubblePriority.CHAT)

    def _on_gateway_disconnected(self, message: str) -> None:
        if self._pending_action is None:
            self._react("sad", message, 2_500, priority=BubblePriority.ERROR)

    def _on_gateway_event(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("type")
        if event_type == "ready":
            self._react("attention", "爱弥斯已作为 Hermes 桌面终端上线。", 1_800, priority=BubblePriority.CHAT)
        elif event_type == "status":
            state = str(payload.get("state", "thinking"))
            self._load_animation(GATEWAY_ANIMATIONS.get(state, "thinking"))
            content = str(payload.get("content", ""))
            if content:
                self.conversation.show_status(content, expand=True)
                self._on_conversation_activity()
        elif event_type == "draft":
            self._load_animation("thinking")
            self.conversation.update_assistant_draft(str(payload.get("content", "")))
        elif event_type == "message":
            self._native_pulse.activate()
            self._load_animation("attention")
            self.conversation.finalize_assistant(str(payload.get("content", "")))
            self._settle_timer.start(5_000)
        elif event_type in {"approval_request", "clarify_request", "slash_confirm"}:
            self._show_native_action(payload)

    def _show_native_action(self, payload: dict[str, Any]) -> None:
        self._pending_action = payload
        self._settle_timer.stop()
        self._load_animation("question")
        question = str(payload.get("question") or payload.get("title") or "Hermes 需要你的确认。")
        command = payload.get("command")
        if isinstance(command, str) and command:
            question = f"{question}\n{command}"
        primary = "选择" if payload.get("type") == "clarify_request" else "批准"
        cancel = "取消" if payload.get("type") == "clarify_request" else "拒绝"
        self.conversation.show_action(question, primary, cancel)
        self._layout_window()

    def _clear_native_action(self) -> None:
        self._pending_action = None
        self.conversation.clear_action()
        self._bubble_scheduler.clear_lock()
        self._on_conversation_activity()

    def confirm_pending_action(self) -> None:
        action = self._pending_action
        if action is None:
            return
        kind = action.get("type")
        if kind == "approval_request":
            self._gateway.resolve_approval(str(action.get("session_key", "")), "approve")
        elif kind == "clarify_request":
            choices = [str(item) for item in action.get("choices", []) if str(item)]
            if choices:
                choice, accepted = QInputDialog.getItem(self, "Hermes 需要选择", str(action.get("question", "")), choices, 0, False)
            else:
                choice, accepted = QInputDialog.getText(self, "Hermes 需要回答", str(action.get("question", "")))
            if not accepted or not choice.strip():
                return
            self._gateway.resolve_clarify(str(action.get("clarify_id", "")), choice.strip())
        elif kind == "slash_confirm":
            self._gateway.resolve_slash_confirm(str(action.get("confirm_id", "")), "once")
        self._clear_native_action()
        self._react("attention", "已发送给 Hermes。", 1_500, priority=BubblePriority.CHAT)

    def cancel_pending_action(self) -> None:
        action = self._pending_action
        if action is None:
            return
        kind = action.get("type")
        if kind == "approval_request":
            self._gateway.resolve_approval(str(action.get("session_key", "")), "deny")
        elif kind == "slash_confirm":
            self._gateway.resolve_slash_confirm(str(action.get("confirm_id", "")), "cancel")
        self._clear_native_action()
        self._react("attention", "已取消。", 1_500, priority=BubblePriority.CHAT)

    def enterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._register_activity()
        if self._drag_offset is None and not self._settle_timer.isActive():
            self._react("notice", "我在这里。", 1_500)
        super().enterEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._register_activity()
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_started = False
            self._react("notice", "请问有什么吩咐？", 1_500)
            event.accept()
        elif event.button() == Qt.RightButton:
            self._show_menu()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            if not self._drag_started:
                self._drag_started = True
                self._settle_timer.stop()
                self._load_animation("drag")
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            dragged = self._drag_started
            self._drag_offset = None
            self._drag_started = False
            self._register_activity()
            self._react("move" if dragged else "attention", "位置已更新。" if dragged else "我在听。", 1_200)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _show_menu(self) -> None:
        menu = QMenu(self)
        chat = QAction("和 Hermes 聊天", self)
        chat.triggered.connect(self.open_chat)
        menu.addAction(chat)
        settings = QAction("设置", self)
        settings.triggered.connect(self.open_settings)
        menu.addAction(settings)
        pause = QAction("暂停动画" if not self._paused else "继续动画", self)
        pause.triggered.connect(self.toggle_pause)
        menu.addAction(pause)
        quit_action = QAction("退出桌宠", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        menu.exec(QCursor.pos())

    def toggle_pause(self) -> None:
        if self._movie is None:
            return
        if self._movie.state() == QMovie.Running:
            self._movie.setPaused(True)
            self._paused = True
            self._speak("动画已暂停。")
        else:
            self._movie.setPaused(False)
            self._paused = False
            self._speak("继续播放。")

    def open_chat(self) -> None:
        self.conversation.expand(focus_input=True)

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.preferences,
            self._settings_store,
            self._startup_manager,
            self._hermes_settings,
            self.apply_preferences,
            self,
            onboard=self.open_onboarding,
        )
        dialog.exec()

    def open_onboarding(self) -> None:
        from .onboarding import OnboardingDialog

        if OnboardingDialog(self._runtime, self).exec():
            self._speak("模型服务已更新，爱弥斯正在重新连接 Hermes。", BubblePriority.CHAT)

    def _send_chat_message(self, text: str) -> None:
        self._register_activity()
        self.conversation.add_user_message(text)
        self._load_animation("busy")
        self.conversation.show_status("消息已交给 Hermes…")
        if not self._gateway.send_user_message(text):
            self._react("sad", "Hermes Gateway 尚未就绪。", 3_000, priority=BubblePriority.ERROR)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._gateway.close()
        super().closeEvent(event)
