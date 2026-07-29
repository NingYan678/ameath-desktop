"""Timer and selection orchestration for the local companion surface."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from .activity_monitor import ActivityMonitor
from .animation_catalog import MICRO_MOTIONS
from .companion_behavior import CompanionBehavior
from .pet_state import CLICK_INTERACTIONS, DRAG_INTERACTIONS, CompanionInteraction, PetStateEngine
from .preferences import DesktopPreferences

LOGGER = logging.getLogger("digital_pet.runtime")


class CompanionController(QObject):
    """Own local motion timers while the window remains a presentation shell."""

    def __init__(
        self,
        preferences: DesktopPreferences,
        pet_state: PetStateEngine,
        activity_monitor: ActivityMonitor,
        behavior: CompanionBehavior,
        *,
        load_animation: Callable[[str], bool],
        react: Callable[[str, str, int], bool],
        is_game_mode: Callable[[], bool],
        is_paused: Callable[[], bool],
        is_dragging: Callable[[], bool],
        has_pending_action: Callable[[], bool],
        is_settling: Callable[[], bool],
        is_conversation_expanded: Callable[[], bool],
        set_auto_game_mode: Callable[[bool], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.preferences = preferences
        self.pet_state = pet_state
        self.activity_monitor = activity_monitor
        self.behavior = behavior
        self._load_animation = load_animation
        self._react = react
        self._is_game_mode = is_game_mode
        self._is_paused = is_paused
        self._is_dragging = is_dragging
        self._has_pending_action = has_pending_action
        self._is_settling = is_settling
        self._is_conversation_expanded = is_conversation_expanded
        self._set_auto_game_mode = set_auto_game_mode

        self.motion_timer = self._single_shot(18_000, self._trigger_micro_motion)
        self.proactive_timer = self._single_shot(0, self._trigger_proactive)
        self.hover_timer = self._single_shot(700, self._trigger_hover_motion)
        self.hover_cooldown_timer = self._single_shot(0, lambda: None)
        self.click_timer = self._single_shot(180, lambda: self.trigger_interaction(CLICK_INTERACTIONS))

    def _single_shot(self, interval: int, callback: Callable[[], None]) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        if interval:
            timer.setInterval(interval)
        timer.timeout.connect(callback)
        return timer

    def start(self) -> None:
        self.schedule_proactive()
        self.schedule_micro_motion()

    def update_preferences(self, preferences: DesktopPreferences) -> None:
        changed = (
            self.preferences.proactive_enabled != preferences.proactive_enabled
            or self.preferences.proactive_max_interval_minutes != preferences.proactive_max_interval_minutes
        )
        self.preferences = preferences
        if changed:
            self.schedule_proactive()

    def record_user_interaction(self, *, schedule: bool = True) -> None:
        self.pet_state.record_interaction()
        if schedule:
            self.schedule_proactive()

    def schedule_micro_motion(self) -> None:
        self.motion_timer.stop()
        self.motion_timer.start(random.randint(18_000, 35_000))

    def _trigger_micro_motion(self) -> None:
        blocked = (
            self._is_game_mode()
            or self._is_paused()
            or self._is_dragging()
            or self._has_pending_action()
            or self._is_settling()
        )
        if not blocked:
            self._load_animation(self.behavior.choose_motion(MICRO_MOTIONS))
        self.schedule_micro_motion()

    def schedule_proactive(self) -> None:
        self.proactive_timer.stop()
        if self.preferences.proactive_enabled:
            delay = self.pet_state.proactive_delay_ms()
            LOGGER.info("Ameath proactive interaction scheduled in %d ms", delay)
            self.proactive_timer.start(delay)

    def _trigger_proactive(self) -> None:
        auto_fullscreen = self.preferences.auto_game_mode and self.activity_monitor.fullscreen_foreground()
        fullscreen = self._is_game_mode() or auto_fullscreen
        self._set_auto_game_mode(auto_fullscreen)
        blocked = self._is_paused() or self._is_dragging() or self._has_pending_action() or self._is_settling()
        if not blocked:
            event = self.pet_state.proactive_event(fullscreen=fullscreen, busy=self._is_conversation_expanded())
            if event is not None and self._react(event.animation, event.text, 4_000):
                self.pet_state.record_proactive(event)
                LOGGER.info("Ameath proactive interaction displayed: %s", event.event_id)
            elif event is not None:
                LOGGER.info("Ameath proactive interaction deferred by bubble priority: %s", event.event_id)
        self.schedule_proactive()

    def trigger_proactive_now(self) -> bool:
        if self._is_paused() or self._is_dragging() or self._has_pending_action():
            self._react("attention", "等我忙完眼前这件事，就马上来找你。", 2_000)
            return False
        event = self.pet_state.proactive_event(fullscreen=False, busy=self._is_conversation_expanded(), manual=True)
        if event is None:
            self._react("attention", "我现在没法分心，稍等我一下。", 2_000)
            return False
        shown = self._react(event.animation, event.text, 4_000)
        if shown:
            self.pet_state.record_proactive(event)
        self.schedule_proactive()
        return shown

    def enter_hover(self) -> None:
        if not self.hover_cooldown_timer.isActive():
            self.hover_timer.start()

    def leave_hover(self) -> None:
        self.hover_timer.stop()

    def _trigger_hover_motion(self) -> None:
        if self._is_dragging() or self._has_pending_action() or self._is_paused() or self._is_settling():
            return
        self._load_animation("curious_peek")
        self.hover_cooldown_timer.start(20_000)

    def cancel_click(self) -> None:
        self.click_timer.stop()

    def schedule_click(self) -> None:
        self.click_timer.start()

    def trigger_interaction(self, catalogue: tuple[CompanionInteraction, ...]) -> None:
        if self._has_pending_action() or self._is_paused():
            return
        item = self.behavior.choose_interaction(catalogue)
        self._react(item.animation, item.text, item.duration_ms)

    def trigger_drag_interaction(self) -> None:
        self.trigger_interaction(DRAG_INTERACTIONS)
