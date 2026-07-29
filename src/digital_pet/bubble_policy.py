"""Priority rules for short desktop status bubbles."""

from __future__ import annotations

import time
from enum import IntEnum


class BubblePriority(IntEnum):
    IDLE = 10
    ACTIVITY = 20
    CHAT = 40
    REMINDER = 70
    CONFIRMATION = 80
    ERROR = 90


class BubbleScheduler:
    """Reject low-priority bubble churn during a short display lock."""

    def __init__(self, minimum_display_ms: int = 800) -> None:
        self.minimum_display_ms = minimum_display_ms
        self._priority = BubblePriority.IDLE
        self._locked_until = 0.0

    def should_show(self, priority: BubblePriority, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else now
        if priority >= self._priority or current_time >= self._locked_until:
            self._priority = priority
            self._locked_until = current_time + self.minimum_display_ms / 1_000
            return True
        return False

    def clear_lock(self) -> None:
        self._priority = BubblePriority.IDLE
        self._locked_until = 0.0
