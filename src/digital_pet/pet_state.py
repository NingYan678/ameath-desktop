"""Local, non-punitive companion state and proactive-interaction policy."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from .preferences import DesktopPreferences
from .storage import atomic_write_json


@dataclass(frozen=True)
class PetState:
    schema_version: int = 1
    familiarity: int = 0
    energy: str = "calm"
    mood: str = "calm"
    last_interaction: str = ""
    last_proactive: str = ""
    proactive_day: str = ""
    proactive_count: int = 0


class PetStateStore:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "pet_state.json"

    def load(self) -> PetState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return PetState(
                familiarity=max(0, min(10_000, int(payload.get("familiarity", 0)))),
                energy=str(payload.get("energy", "calm")),
                mood=str(payload.get("mood", "calm")),
                last_interaction=str(payload.get("last_interaction", "")),
                last_proactive=str(payload.get("last_proactive", "")),
                proactive_day=str(payload.get("proactive_day", "")),
                proactive_count=max(0, int(payload.get("proactive_count", 0))),
            )
        except (OSError, ValueError, TypeError):
            return PetState()

    def save(self, state: PetState) -> None:
        atomic_write_json(self.path, asdict(state))


class PetStateEngine:
    """Keeps companion behavior gentle: familiarity never decays and never punishes absence."""

    def __init__(self, store: PetStateStore, preferences: DesktopPreferences) -> None:
        self.store = store
        self.preferences = preferences
        self.state = store.load()

    def update_preferences(self, preferences: DesktopPreferences) -> None:
        self.preferences = preferences

    def record_interaction(self, now: datetime | None = None) -> None:
        moment = now or datetime.now()
        self.state = replace(self.state, familiarity=min(10_000, self.state.familiarity + 1), last_interaction=moment.isoformat(), energy="engaged", mood="curious")
        self.store.save(self.state)

    def proactive_message(self, *, fullscreen: bool, busy: bool, now: datetime | None = None) -> str | None:
        moment = now or datetime.now()
        if not self.preferences.proactive_enabled or self.preferences.do_not_disturb or fullscreen or busy:
            return None
        if self._quiet(moment) or self.preferences.proactive_daily_limit == 0:
            return None
        day = moment.date().isoformat()
        count = self.state.proactive_count if self.state.proactive_day == day else 0
        if count >= self.preferences.proactive_daily_limit:
            return None
        if self.state.last_proactive:
            try:
                if moment - datetime.fromisoformat(self.state.last_proactive) < timedelta(minutes=90):
                    return None
            except ValueError:
                pass
        text = "辛苦啦，记得让眼睛休息一下。" if count % 2 == 0 else "我在这里陪着你，需要时叫我就好。"
        self.state = replace(self.state, mood="curious", last_proactive=moment.isoformat(), proactive_day=day, proactive_count=count + 1)
        self.store.save(self.state)
        return text

    def _quiet(self, moment: datetime) -> bool:
        start, end, hour = self.preferences.quiet_start_hour, self.preferences.quiet_end_hour, moment.hour
        return start <= hour < end if start < end else hour >= start or hour < end
