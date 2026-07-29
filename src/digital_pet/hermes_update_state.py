"""Persistent state and value types for Hermes update operations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .config import Settings
from .runtime_descriptor import RuntimeHealth
from .storage import atomic_write_json

OFFICIAL_REPOSITORY = "https://github.com/NousResearch/hermes-agent.git"
OFFICIAL_ARCHIVE = "https://github.com/NousResearch/hermes-agent/archive/{revision}.zip"
CHECK_INTERVAL = timedelta(hours=24)
OFFLINE_RETRY_INTERVAL = timedelta(hours=6)


class HermesUpdateStatus(StrEnum):
    IDLE = "idle"
    CHECKING = "checking"
    AVAILABLE = "available"
    UPDATING = "updating"
    VERIFYING = "verifying"
    FAILED = "failed"


@dataclass(frozen=True)
class HermesUpdateInfo:
    current_revision: str
    target_revision: str
    source_url: str
    runtime_kind: str
    update_available: bool
    checked_at: str
    current_branch: str = ""


@dataclass(frozen=True)
class HermesUpdateResult:
    previous_revision: str
    current_revision: str
    updated: bool
    log_path: Path
    runtime_root: Path | None = None


@dataclass(frozen=True)
class HermesUpdateState:
    last_checked_at: str = ""
    retry_after: str = ""
    target_revision: str = ""
    notified_revision: str = ""
    last_error: str = ""


class UpdateRuntime(Protocol):
    settings: Settings

    def stop_gateway(self) -> bool: ...
    def switch_runtime(self, runtime_root: Path) -> None: ...
    def prepare(self) -> None: ...
    def start_gateway(self) -> bool: ...
    def verify_identity(self) -> RuntimeHealth: ...


class HermesUpdateStateStore:
    """Persist non-secret scheduling and notification state."""

    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "hermes_update_state.json"

    def load(self) -> HermesUpdateState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            return HermesUpdateState(
                last_checked_at=str(payload.get("last_checked_at", "")),
                retry_after=str(payload.get("retry_after", "")),
                target_revision=str(payload.get("target_revision", "")),
                notified_revision=str(payload.get("notified_revision", "")),
                last_error=str(payload.get("last_error", "")),
            )
        except (OSError, ValueError, TypeError):
            return HermesUpdateState()

    def save(self, state: HermesUpdateState) -> None:
        atomic_write_json(self.path, asdict(state))

    def check_due(self, now: datetime | None = None) -> bool:
        state = self.load()
        current = now or datetime.now(UTC)
        retry = parse_time(state.retry_after)
        checked = parse_time(state.last_checked_at)
        if retry is not None:
            return current >= retry
        return checked is None or current - checked >= CHECK_INTERVAL


def parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None
