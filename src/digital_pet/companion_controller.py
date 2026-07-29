"""Timer and selection orchestration for the local companion surface."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from .activity_monitor import ActivityMonitor
from .companion_behavior import CompanionBehavior
from .companion_sequences import MOTION_SEQUENCES, SEQUENCE_BY_ANIMATION, MotionSequence
from .pet_state import CLICK_INTERACTIONS, DRAG_INTERACTIONS, CompanionInteraction, PetStateEngine, ProactiveEvent
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
        show_proactive_prompt: Callable[[ProactiveEvent | None], None],
        reduced_motion: Callable[[], bool],
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
        self._show_proactive_prompt = show_proactive_prompt
        self._reduced_motion = reduced_motion
        self._active_sequence: MotionSequence | None = None
        self._sequence_index = 0
        self._lifecycle_paused = False
        self._sequence_started_at: dict[str, float] = {}

        self.motion_timer = self._single_shot(18_000, self._trigger_micro_motion)
        self.proactive_timer = self._single_shot(0, self._trigger_proactive)
        self.hover_timer = self._single_shot(700, self._trigger_hover_motion)
        self.hover_cooldown_timer = self._single_shot(0, lambda: None)
        self.click_timer = self._single_shot(180, lambda: self.trigger_interaction(CLICK_INTERACTIONS))
        self.sequence_timer = self._single_shot(0, self._run_sequence_step)

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

    def set_lifecycle_paused(self, paused: bool) -> None:
        self._lifecycle_paused = paused
        if paused:
            self.motion_timer.stop()
            self.proactive_timer.stop()
            self.sequence_timer.stop()
            self._active_sequence = None
        else:
            self.schedule_micro_motion()
            self.schedule_proactive()

    def update_preferences(self, preferences: DesktopPreferences) -> None:
        changed = (
            self.preferences.proactive_enabled != preferences.proactive_enabled
            or self.preferences.proactive_max_interval_minutes != preferences.proactive_max_interval_minutes
            or self.preferences.reduced_motion != preferences.reduced_motion
        )
        if preferences.reduced_motion and not self.preferences.reduced_motion:
            self.sequence_timer.stop()
            self._active_sequence = None
        self.preferences = preferences
        if changed:
            self.schedule_proactive()

    def record_user_interaction(self, *, schedule: bool = True) -> None:
        self.pet_state.record_interaction()
        if schedule:
            self.schedule_proactive()

    def schedule_micro_motion(self) -> None:
        self.motion_timer.stop()
        if not self._lifecycle_paused:
            self.motion_timer.start(random.randint(18_000, 35_000))

    def _trigger_micro_motion(self) -> None:
        blocked = (
            self._is_game_mode()
            or self._is_paused()
            or self._is_dragging()
            or self._has_pending_action()
            or self._is_settling()
            or self._active_sequence is not None
            or self._lifecycle_paused
        )
        if not blocked and not self._reduced_motion():
            self.play_sequence()
        self.schedule_micro_motion()

    def play_sequence(self, sequence_id: str | None = None, *, animation: str | None = None) -> bool:
        if self._reduced_motion() or self._lifecycle_paused:
            return False
        if sequence_id is None and animation is not None:
            sequence_id = SEQUENCE_BY_ANIMATION.get(animation)
        sequence = next((item for item in MOTION_SEQUENCES if item.sequence_id == sequence_id), None) if sequence_id else None
        if sequence is None:
            sequence = self.behavior.choose_sequence(minimum_stage=self.pet_state.relationship_stage())
        started = self._sequence_started_at.get(sequence.sequence_id, 0.0)
        if sequence.cooldown_ms and (time.monotonic() - started) * 1_000 < sequence.cooldown_ms:
            return False
        self._active_sequence = sequence
        self._sequence_started_at[sequence.sequence_id] = time.monotonic()
        self._sequence_index = 0
        self.sequence_timer.stop()
        self._run_sequence_step()
        return True

    def _run_sequence_step(self) -> None:
        sequence = self._active_sequence
        if sequence is None or self._sequence_index >= len(sequence.steps):
            self._active_sequence = None
            self._sequence_index = 0
            return
        step = sequence.steps[self._sequence_index]
        self._sequence_index += 1
        self._load_animation(step.animation)
        self.sequence_timer.start(step.duration_ms)

    def schedule_proactive(self) -> None:
        self.proactive_timer.stop()
        if self.preferences.proactive_enabled and not self._lifecycle_paused:
            delay = self.pet_state.proactive_delay_ms()
            LOGGER.info("Ameath proactive interaction scheduled in %d ms", delay)
            self.proactive_timer.start(delay)

    def _trigger_proactive(self) -> None:
        auto_fullscreen = self.preferences.auto_game_mode and self.activity_monitor.fullscreen_foreground()
        fullscreen = self._is_game_mode() or auto_fullscreen
        self._set_auto_game_mode(auto_fullscreen)
        blocked = self._lifecycle_paused or self._is_paused() or self._is_dragging() or self._has_pending_action() or self._is_settling()
        if not blocked:
            event = self.pet_state.proactive_event(fullscreen=fullscreen, busy=self._is_conversation_expanded())
            if event is not None and self._react(event.animation, event.text, 4_000):
                self.pet_state.record_proactive(event)
                self._show_proactive_prompt(event)
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
            self._show_proactive_prompt(event)
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
        self.play_sequence("hover-peek")
        self.hover_cooldown_timer.start(20_000)

    def cancel_click(self) -> None:
        self.click_timer.stop()

    def schedule_click(self) -> None:
        self.click_timer.start()

    def trigger_interaction(self, catalogue: tuple[CompanionInteraction, ...]) -> None:
        if self._has_pending_action() or self._is_paused():
            return
        item = self.behavior.choose_interaction(catalogue)
        self.play_sequence(animation=item.animation)
        self._react(item.animation, item.text, item.duration_ms)

    def trigger_drag_interaction(self) -> None:
        self.trigger_interaction(DRAG_INTERACTIONS)
