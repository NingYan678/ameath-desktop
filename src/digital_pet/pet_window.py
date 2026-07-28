from __future__ import annotations

import logging
import random
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QMovie, QPainter, QPen
from PySide6.QtWidgets import QInputDialog, QLabel, QWidget

from .ameath_runtime import AmeathRuntimeService
from .activity_monitor import ActivityMonitor
from .butler_protocol import BubblePriority, BubbleScheduler, PET_STATE_ANIMATIONS
from .config import PROJECT_ROOT, Settings
from .conversation_panel import ConversationPanel
from .hermes_desktop_client import HermesDesktopClient
from .hermes_settings import HermesSettingsService
from .preferences import DesktopPreferences, StartupManager, UISettingsStore
from .pet_state import CLICK_INTERACTIONS, DRAG_INTERACTIONS, CompanionInteraction, PetStateEngine, PetStateStore
from .runtime_supervisor import RuntimeSupervisor
from .settings_dialog import SettingsDialog


ANIMATIONS = {
    "idle_soft": "screen3.gif", "idle_alert": "screen1.gif", "idle_happy": "sd_idle_happy.gif", "idle_sleepy": "screen6.gif",
    "move": "sd_move.gif", "drag": "sd_drag.gif", "notice": "screen1.gif", "sad": "screen2.gif",
    "attention": "screen3.gif", "thinking": "screen4.gif", "busy": "screen5.gif", "rest": "screen6.gif",
    "question": "screen7.gif", "music": "ameath.gif",
    "blink": "sd_blink.gif", "look_left": "sd_look_left.gif", "look_right": "sd_look_right.gif",
    "breathe": "sd_breathe.gif", "sway": "sd_sway.gif", "float": "sd_float.gif",
    "greeting": "sd_greeting.gif", "curious_peek": "sd_curious_peek.gif", "surprised": "sd_surprised.gif",
    "sleepy_stretch": "sd_sleepy_stretch.gif",
    "paper_plane": "sd_paper_plane.gif", "sparkle_happy": "sd_sparkle_happy.gif",
}
ANIMATION_LABELS = {
    "idle_soft": "待机：眨眼", "idle_alert": "待机：注意", "idle_happy": "待机：微笑", "idle_sleepy": "待机：困倦",
    "move": "移动过渡", "drag": "拖动反馈", "notice": "关注你", "sad": "难过", "attention": "回应你",
    "thinking": "思考", "busy": "专注", "rest": "休息", "question": "等待指令", "music": "小小音乐会",
    "blink": "眨眼", "look_left": "左顾", "look_right": "右盼", "breathe": "轻呼吸", "sway": "轻摇摆", "float": "漂浮",
    "greeting": "歪头招呼", "curious_peek": "探头", "surprised": "惊讶", "sleepy_stretch": "困倦伸展",
    "paper_plane": "纸飞机", "sparkle_happy": "闪光开心",
}
IDLE_ANIMATIONS = ("idle_soft", "idle_alert", "idle_happy", "idle_sleepy")
MICRO_MOTIONS = ("blink", "look_left", "look_right", "breathe", "sway", "float", "greeting", "curious_peek", "surprised", "sleepy_stretch", "paper_plane", "sparkle_happy")
LOGGER = logging.getLogger("digital_pet.runtime")
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
    context_menu_requested = Signal()
    proactive_changed = Signal(bool)
    PET_SIZE = 200

    def __init__(
        self,
        settings: Settings,
        runtime: AmeathRuntimeService | None = None,
        *,
        shared_hermes: bool = False,
        backend_reconfigure: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.setWindowIcon(QIcon(str(settings.asset_root / "gifs" / "ameath.ico")))
        self._settings_store = UISettingsStore(settings.data_root)
        self.preferences = self._settings_store.load()
        self._pet_state = PetStateEngine(PetStateStore(settings.data_root), self.preferences)
        self._activity_monitor = ActivityMonitor()
        self._startup_manager = StartupManager(settings.launch_command)
        self._runtime = runtime or AmeathRuntimeService(settings)
        self._shared_hermes = shared_hermes
        self._backend_reconfigure = backend_reconfigure
        self._close_handler: Callable[[], bool] | None = None
        self._auto_game_mode = False
        self._manual_game_mode = False
        self._hermes_settings = HermesSettingsService(
            settings.hermes_home,
            python=settings.hermes_cli_python,
            source=settings.hermes_source,
            restart_handler=self._runtime.restart_gateway,
        )
        self._drag_offset: QPoint | None = None
        self._drag_started = False
        self._movie: QMovie | None = None
        self._movie_cache: dict[str, QMovie] = {}
        self._bubble_scheduler = BubbleScheduler()
        self._pending_action: dict[str, Any] | None = None
        self._current_animation = "idle_soft"
        self._paused = False
        self._recent_motion_ids: list[str] = []
        self._recent_interaction_ids: list[str] = []
        self._gateway = HermesDesktopClient(settings, self)
        self._gateway.connected.connect(self._on_gateway_connected)
        self._gateway.disconnected.connect(self._on_gateway_disconnected)
        self._gateway.event_received.connect(self._on_gateway_event)
        self._supervisor = RuntimeSupervisor(self._runtime, shared=shared_hermes, parent=self)
        self._supervisor.status_changed.connect(self._on_supervisor_status)
        self._supervisor.connection_allowed.connect(self._on_connection_allowed)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._return_to_idle)
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(5_000)
        self._idle_timer.timeout.connect(self._auto_switch)
        self._motion_timer = QTimer(self)
        self._motion_timer.setSingleShot(True)
        self._motion_timer.timeout.connect(self._trigger_micro_motion)
        self._proactive_timer = QTimer(self)
        self._proactive_timer.setSingleShot(True)
        self._proactive_timer.timeout.connect(self._trigger_proactive)
        self._rest_timer = QTimer(self)
        self._rest_timer.setSingleShot(True)
        self._rest_timer.timeout.connect(self._rest_after_inactivity)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(700)
        self._hover_timer.timeout.connect(self._trigger_hover_motion)
        self._hover_cooldown_timer = QTimer(self)
        self._hover_cooldown_timer.setSingleShot(True)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(180)
        self._click_timer.timeout.connect(self._trigger_click_interaction)
        self._conversation_timer = QTimer(self)
        self._conversation_timer.setSingleShot(True)
        self._conversation_timer.timeout.connect(self._collapse_conversation_when_idle)
        self._position_timer = QTimer(self)
        self._position_timer.setSingleShot(True)
        self._position_timer.timeout.connect(self._persist_position)

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
        self._restore_window_position()
        if not self._load_animation(self._current_animation):
            self.pet.setText("未找到本地角色素材")
            self.pet.setStyleSheet("color: white; background: rgba(20, 30, 48, 160); border-radius: 16px;")
        self._speak("正在连接 Hermes Gateway…", BubblePriority.ACTIVITY)
        self._idle_timer.start()
        self._schedule_proactive()
        self._schedule_micro_motion()
        self._register_activity()
        self._supervisor.start()

    def _asset(self, filename: str) -> Path:
        return self.settings.asset_root / "gifs" / filename

    def _load_animation(self, name: str) -> bool:
        source = self._asset(ANIMATIONS[name])
        if not source.exists():
            return False
        movie = self._movie_cache.get(name)
        if movie is None:
            movie = QMovie(str(source), parent=self)
            movie.setScaledSize(QSize(self.preferences.pet_size, self.preferences.pet_size))
            movie.setSpeed(self.preferences.animation_speed)
            if not movie.isValid():
                movie.deleteLater()
                return False
            self._movie_cache[name] = movie
        if self._movie is not None and self._movie is not movie:
            self._movie.stop()
        self._movie = movie
        self.pet.setMovie(movie)
        movie.start()
        self._current_animation = name
        self._paused = False
        return True

    def apply_preferences(self, preferences: DesktopPreferences, *, update_window_flags: bool = True) -> None:
        previous = self.preferences
        self.preferences = preferences
        self._pet_state.update_preferences(preferences)
        self.conversation.apply_preferences(preferences)
        for movie in self._movie_cache.values():
            movie.setScaledSize(QSize(preferences.pet_size, preferences.pet_size))
            movie.setSpeed(preferences.animation_speed)
        if update_window_flags:
            self._refresh_window_flags()
        self._layout_window()
        if (
            previous.proactive_enabled != preferences.proactive_enabled
            or previous.proactive_max_interval_minutes != preferences.proactive_max_interval_minutes
        ):
            self._schedule_proactive()

    @property
    def game_mode_active(self) -> bool:
        return self._manual_game_mode or self._auto_game_mode

    def _refresh_window_flags(self) -> None:
        """Changing flags hides a Qt window, so capture visibility beforehand."""
        was_visible = self.isVisible()
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.preferences.always_on_top and not self.game_mode_active:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

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

    def _react(self, animation: str, text: str, duration_ms: int = 2_000, *, priority: BubblePriority = BubblePriority.ACTIVITY) -> bool:
        self._settle_timer.stop()
        self._load_animation(animation)
        shown = self._speak(text, priority)
        self._settle_timer.start(duration_ms)
        return shown

    def _speak(self, text: str, priority: BubblePriority = BubblePriority.ACTIVITY) -> bool:
        if self._bubble_scheduler.should_show(priority):
            self.conversation.show_status(text)
            return True
        return False

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
        fullscreen = self.preferences.auto_game_mode and self._activity_monitor.fullscreen_foreground()
        self._set_auto_game_mode(fullscreen)
        if self._paused or self._drag_offset is not None or self._pending_action is not None or self._settle_timer.isActive():
            return
        self._load_animation(random.choice(IDLE_ANIMATIONS))

    def _schedule_micro_motion(self) -> None:
        self._motion_timer.stop()
        self._motion_timer.start(random.randint(18_000, 35_000))

    def _trigger_micro_motion(self) -> None:
        blocked = self.game_mode_active or self._paused or self._drag_offset is not None or self._pending_action is not None or self._settle_timer.isActive()
        if blocked:
            self._motion_timer.start(5_000)
            return
        available = [name for name in MICRO_MOTIONS if name not in self._recent_motion_ids]
        motion = random.choice(available or list(MICRO_MOTIONS))
        self._recent_motion_ids = (*self._recent_motion_ids, motion)[-4:]
        self._load_animation(motion)
        self._settle_timer.start(1_900)
        self._schedule_micro_motion()

    def _schedule_proactive(self) -> None:
        self._proactive_timer.stop()
        if self.preferences.proactive_enabled:
            delay = self._pet_state.proactive_delay_ms()
            LOGGER.info("Ameath proactive interaction scheduled in %d ms", delay)
            self._proactive_timer.start(delay)

    def _trigger_proactive(self) -> None:
        auto_fullscreen = self.preferences.auto_game_mode and self._activity_monitor.fullscreen_foreground()
        fullscreen = self.game_mode_active or auto_fullscreen
        self._set_auto_game_mode(auto_fullscreen)
        blocked = self._paused or self._drag_offset is not None or self._pending_action is not None or self._settle_timer.isActive()
        if blocked:
            LOGGER.info("Ameath proactive interaction deferred: transient UI activity")
            self._proactive_timer.start(5_000)
            return
        event = self._pet_state.proactive_event(fullscreen=fullscreen, busy=self.conversation.is_expanded)
        if event is None:
            LOGGER.info("Ameath proactive interaction suppressed by a protected state")
            self._schedule_proactive()
            return
        if self._react(event.animation, event.text, 4_000):
            self._pet_state.record_proactive(event)
            LOGGER.info("Ameath proactive interaction displayed: %s", event.event_id)
        else:
            LOGGER.info("Ameath proactive interaction deferred by bubble priority: %s", event.event_id)
            self._proactive_timer.start(5_000)
            return
        self._schedule_proactive()

    def trigger_proactive_now(self) -> bool:
        """Show one locally authored companion moment on the user's request."""
        if self._paused or self._drag_offset is not None or self._pending_action is not None:
            self._speak("等我忙完眼前这件事，就马上来找你。")
            return False
        event = self._pet_state.proactive_event(fullscreen=False, busy=self.conversation.is_expanded, manual=True)
        if event is None:
            self._speak("我现在没法分心，稍等我一下。")
            return False
        if self._react(event.animation, event.text, 4_000):
            self._pet_state.record_proactive(event)
        self._schedule_proactive()
        return True

    def _note_user_interaction(self) -> None:
        self._pet_state.record_interaction()
        self._schedule_proactive()

    def _set_auto_game_mode(self, enabled: bool) -> None:
        if enabled == self._auto_game_mode:
            return
        self._auto_game_mode = enabled
        self._refresh_window_flags()
        if enabled:
            self._speak("检测到全屏应用，已暂停主动互动。")

    def toggle_game_mode(self) -> None:
        """Manual game mode is session-only and never rewrites user preferences."""
        self._manual_game_mode = not self._manual_game_mode
        self._refresh_window_flags()
        self._speak("已开启游戏模式。" if self._manual_game_mode else "已恢复置顶显示。")

    def toggle_proactive(self) -> None:
        preferences = replace(self.preferences, proactive_enabled=not self.preferences.proactive_enabled)
        self._save_preferences(preferences)
        self.proactive_changed.emit(preferences.proactive_enabled)
        self._speak("已暂停主动互动。" if not preferences.proactive_enabled else "已恢复适度主动陪伴。")

    def reconnect_gateway(self) -> None:
        self._supervisor.reconnect_now()
        self._speak("正在检查 Hermes Gateway。")

    def _on_connection_allowed(self, allowed: bool) -> None:
        if allowed:
            self._gateway.start()
        else:
            self._gateway.close()

    def _on_supervisor_status(self, status: str) -> None:
        if not self._gateway.is_connected:
            self._speak(status)

    def _save_preferences(self, preferences: DesktopPreferences) -> None:
        self._settings_store.save(preferences)
        self.apply_preferences(preferences)

    def set_close_handler(self, handler: Callable[[], bool]) -> None:
        self._close_handler = handler

    def _restore_window_position(self) -> None:
        screens = QGuiApplication.screens()
        screen = next((item for item in screens if item.name() == self.preferences.window_screen), None)
        screen = screen or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        if self.preferences.window_x < 0 or self.preferences.window_y < 0:
            self.move(area.center() - self.rect().center())
            return
        x = min(max(self.preferences.window_x, area.left()), area.right() - min(40, self.width()))
        y = min(max(self.preferences.window_y, area.top()), area.bottom() - min(40, self.height()))
        self.move(x, y)

    def moveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if hasattr(self, "_position_timer"):
            self._position_timer.start(350)
        super().moveEvent(event)

    def _persist_position(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        preferences = replace(self.preferences, window_screen=screen.name() if screen is not None else "", window_x=self.x(), window_y=self.y())
        if preferences != self.preferences:
            self._settings_store.save(preferences)
            self.preferences = preferences
            self._pet_state.update_preferences(preferences)

    def _rest_after_inactivity(self) -> None:
        if self._drag_offset is None and self._pending_action is None and not self._paused:
            self._load_animation("sleepy_stretch")
            self._settle_timer.start(2_200)
        self._rest_timer.start(90_000)

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
            self._load_animation(PET_STATE_ANIMATIONS.get(state, "thinking"))
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
        if not self._hover_cooldown_timer.isActive():
            self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hover_timer.stop()
        super().leaveEvent(event)

    def _trigger_hover_motion(self) -> None:
        if self._drag_offset is not None or self._pending_action is not None or self._paused or self._settle_timer.isActive():
            return
        self._load_animation("curious_peek")
        self._settle_timer.start(1_500)
        self._hover_cooldown_timer.start(20_000)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._register_activity()
        if event.button() == Qt.LeftButton:
            self._note_user_interaction()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_started = False
            event.accept()
        elif event.button() == Qt.RightButton:
            self.context_menu_requested.emit()
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
            if dragged:
                self._trigger_interaction(DRAG_INTERACTIONS)
            else:
                self._click_timer.start()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.LeftButton:
            self._click_timer.stop()
            self._note_user_interaction()
            self._react("greeting", "想说点什么吗？", 1_600)
            self.open_chat()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _trigger_click_interaction(self) -> None:
        self._trigger_interaction(CLICK_INTERACTIONS)

    def _trigger_interaction(self, catalogue: tuple[CompanionInteraction, ...]) -> None:
        if self._pending_action is not None or self._paused:
            return
        choices = [item for item in catalogue if item.event_id not in self._recent_interaction_ids]
        item = random.choice(choices or list(catalogue))
        self._recent_interaction_ids = (*self._recent_interaction_ids, item.event_id)[-4:]
        self._react(item.animation, item.text, item.duration_ms)

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

    @property
    def animation_paused(self) -> bool:
        return self._paused

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
            onboard=None if self._shared_hermes else self.open_onboarding,
            shared_hermes=self._shared_hermes,
            backend_reconfigure=self._backend_reconfigure,
            backend_status=str(getattr(self._runtime, "status_summary", "")),
        )
        dialog.exec()

    def open_onboarding(self) -> None:
        from .onboarding import OnboardingDialog

        if OnboardingDialog(self._runtime, self).exec():
            self._speak("模型服务已更新，爱弥斯正在重新连接 Hermes。", BubblePriority.CHAT)

    def _send_chat_message(self, text: str) -> None:
        self._register_activity()
        self._note_user_interaction()
        self.conversation.add_user_message(text)
        self._load_animation("busy")
        self.conversation.show_status("消息已交给 Hermes…")
        if not self._gateway.send_user_message(text):
            self._react("sad", "Hermes Gateway 尚未就绪。", 3_000, priority=BubblePriority.ERROR)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._close_handler is not None and self._close_handler():
            event.ignore()
            return
        self._supervisor.stop()
        self._gateway.close()
        super().closeEvent(event)
