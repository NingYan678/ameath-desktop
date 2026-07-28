"""Stateful selection rules for local companion motions and direct interactions."""

from __future__ import annotations

import random

from .pet_state import CompanionInteraction


class CompanionBehavior:
    def __init__(self) -> None:
        self._recent_motion_ids: list[str] = []
        self._recent_interaction_ids: list[str] = []

    @property
    def recent_motion_ids(self) -> tuple[str, ...]:
        return tuple(self._recent_motion_ids)

    def choose_motion(self, motions: tuple[str, ...]) -> str:
        available = [name for name in motions if name not in self._recent_motion_ids]
        choice = random.choice(available or list(motions))
        self._recent_motion_ids = [*self._recent_motion_ids, choice][-4:]
        return choice

    def choose_interaction(self, catalogue: tuple[CompanionInteraction, ...]) -> CompanionInteraction:
        available = [item for item in catalogue if item.event_id not in self._recent_interaction_ids]
        choice = random.choice(available or list(catalogue))
        self._recent_interaction_ids = [*self._recent_interaction_ids, choice.event_id][-4:]
        return choice
