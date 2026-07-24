from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any


BUTLER_STATES = frozenset(
    {
        "thinking",
        "running",
        "analyzing",
        "building",
        "searching",
        "permission",
        "celebrating",
        "failed",
        "idle",
        "attention",
    }
)

PET_STATE_ANIMATIONS = {
    "thinking": "thinking",
    "running": "busy",
    "analyzing": "thinking",
    "building": "busy",
    "searching": "attention",
    "permission": "question",
    "celebrating": "music",
    "failed": "sad",
    "idle": "idle_soft",
    "attention": "attention",
}


class BubblePriority(IntEnum):
    IDLE = 10
    ACTIVITY = 20
    CHAT = 40
    REMINDER = 70
    CONFIRMATION = 80
    ERROR = 90


@dataclass(frozen=True)
class ButlerProposal:
    action: str
    task_id: str | None = None
    title: str | None = None
    due_at: datetime | None = None


@dataclass(frozen=True)
class ButlerReply:
    reply: str
    state: str = "attention"
    proposal: ButlerProposal | None = None
    structured: bool = False


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


def parse_butler_reply(content: object) -> ButlerReply:
    """Read the narrow JSON contract and safely fall back to plain chat text."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Hermes returned an empty reply.")
    raw = content.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ButlerReply(reply=raw)
    if not isinstance(payload, dict):
        return ButlerReply(reply=raw)
    reply = payload.get("reply")
    state = payload.get("state", "attention")
    if not isinstance(reply, str) or not reply.strip() or not isinstance(state, str) or state not in BUTLER_STATES:
        return ButlerReply(reply=raw)
    try:
        proposal = _parse_proposal(payload.get("proposal"))
    except ValueError:
        proposal = None
    return ButlerReply(reply=reply.strip(), state=state, proposal=proposal, structured=True)


def _parse_proposal(value: Any) -> ButlerProposal | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("proposal must be an object")
    action = value.get("action")
    if action not in {"create_reminder", "update_reminder", "cancel_reminder"}:
        raise ValueError("unsupported proposal action")
    task_id = value.get("task_id")
    title = value.get("title")
    due_at_value = value.get("due_at")
    if task_id is not None and (not isinstance(task_id, str) or not task_id.strip()):
        raise ValueError("invalid task id")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("invalid title")
    due_at = None
    if due_at_value is not None:
        if not isinstance(due_at_value, str):
            raise ValueError("invalid due date")
        due_at = datetime.strptime(due_at_value, "%Y-%m-%d %H:%M")
    if action == "create_reminder" and (not title or due_at is None):
        raise ValueError("create proposal requires title and due_at")
    if action == "update_reminder" and (not task_id or (not title and due_at is None)):
        raise ValueError("update proposal is incomplete")
    if action == "cancel_reminder" and not task_id:
        raise ValueError("cancel proposal requires task_id")
    return ButlerProposal(action=action, task_id=task_id, title=title.strip() if title else None, due_at=due_at)
