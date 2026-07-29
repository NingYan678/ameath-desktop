"""Opt-in, privacy-preserving memory hints for the Ameath companion."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .preferences import DesktopPreferences
from .storage import atomic_write_json

COOLDOWN = timedelta(hours=6)
ALLOWED_CATEGORIES = frozenset({"interest", "goal", "topic"})
_SENSITIVE = re.compile(r"(?i)(token|password|secret|api[_ -]?key|bearer|cookie|c:\\|[a-z]:\\|主人|恋人|身份证|手机号)")


@dataclass(frozen=True)
class CompanionCue:
    request_id: str
    text: str
    category: str
    expires_at: str

    @classmethod
    def from_payload(cls, payload: Any, *, now: datetime | None = None) -> CompanionCue | None:
        if not isinstance(payload, dict):
            return None
        request_id = payload.get("request_id")
        text = payload.get("text")
        category = payload.get("category")
        expires_at = payload.get("expires_at")
        if not all(isinstance(value, str) for value in (request_id, text, category, expires_at)):
            return None
        text = text.strip()
        if not request_id or not 1 <= len(text) <= 120 or category not in ALLOWED_CATEGORIES or _SENSITIVE.search(text):
            return None
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        current = now or datetime.now(UTC)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= current or expires > current + timedelta(days=8):
            return None
        return cls(request_id, text, category, expires.isoformat())


class CueClient(Protocol):
    def request_companion_cue(self, request_id: str, categories: tuple[str, ...]) -> bool: ...


class MemoryCueStore:
    """Persist only request metadata, a digest, and expiry; never cue text."""

    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "companion_cue_state.json"

    def load(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {key: str(value) for key, value in payload.items() if key in {"request_id", "requested_at", "cue_hash", "expires_at"} and isinstance(value, (str, int, float))}

    def save_request(self, request_id: str, requested_at: datetime) -> None:
        previous = self.load()
        previous.update({"request_id": request_id, "requested_at": requested_at.isoformat()})
        atomic_write_json(self.path, previous)

    def save_cue(self, cue: CompanionCue) -> None:
        previous = self.load()
        previous.update({"cue_hash": hashlib.sha256(cue.text.encode("utf-8")).hexdigest(), "expires_at": cue.expires_at})
        previous.pop("text", None)
        atomic_write_json(self.path, previous)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class MemoryCueController:
    """Coordinates explicit consent and six-hour rate limiting."""

    def __init__(self, data_root: Path, preferences: DesktopPreferences) -> None:
        self.store = MemoryCueStore(data_root)
        self.preferences = preferences
        self.pending_request_id = ""

    def update_preferences(self, preferences: DesktopPreferences) -> None:
        self.preferences = preferences

    def can_request(self, now: datetime | None = None) -> bool:
        if not self.preferences.memory_cues_enabled or self.preferences.memory_consent_version < 1:
            return False
        raw = self.store.load().get("requested_at", "")
        if not raw:
            return True
        try:
            requested = datetime.fromisoformat(raw)
        except ValueError:
            return True
        current = now or datetime.now(UTC)
        if requested.tzinfo is None:
            requested = requested.replace(tzinfo=UTC)
        return current - requested >= COOLDOWN

    def request(self, client: CueClient, now: datetime | None = None) -> str | None:
        if not self.can_request(now):
            return None
        current = now or datetime.now(UTC)
        request_id = uuid.uuid4().hex
        self.pending_request_id = request_id
        self.store.save_request(request_id, current)
        if not client.request_companion_cue(request_id, tuple(sorted(ALLOWED_CATEGORIES))):
            self.pending_request_id = ""
            return None
        return request_id

    def accept(self, payload: Any, *, now: datetime | None = None) -> CompanionCue | None:
        cue = CompanionCue.from_payload(payload, now=now)
        if cue is None or cue.request_id != self.pending_request_id:
            return None
        self.pending_request_id = ""
        self.store.save_cue(cue)
        return cue

    def clear_learning_state(self) -> None:
        self.pending_request_id = ""
        self.store.clear()
