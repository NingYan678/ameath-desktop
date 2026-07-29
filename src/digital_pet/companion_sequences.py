"""Small, reusable motion sequences built from the approved Ameath sprites."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MotionStep:
    animation: str
    duration_ms: int


@dataclass(frozen=True)
class MotionSequence:
    sequence_id: str
    steps: tuple[MotionStep, ...]
    minimum_stage: str = "初识"
    priority: int = 0
    trigger_condition: str = "idle"
    cooldown_ms: int = 0


MOTION_SEQUENCES: tuple[MotionSequence, ...] = (
    MotionSequence("greeting", (MotionStep("curious_peek", 420), MotionStep("greeting", 1_100), MotionStep("idle_soft", 500))),
    MotionSequence("hover-peek", (MotionStep("curious_peek", 900), MotionStep("look_left", 700))),
    MotionSequence("drag-landing", (MotionStep("drag", 500), MotionStep("move", 700), MotionStep("attention", 600))),
    MotionSequence("sleepy-evening", (MotionStep("sleepy_stretch", 1_200), MotionStep("breathe", 900), MotionStep("idle_sleepy", 800))),
    MotionSequence("morning-wake", (MotionStep("blink", 450), MotionStep("breathe", 700), MotionStep("idle_happy", 900))),
    MotionSequence("thinking", (MotionStep("look_left", 650), MotionStep("thinking", 1_000), MotionStep("breathe", 600))),
    MotionSequence("celebrate", (MotionStep("surprised", 500), MotionStep("sparkle_happy", 1_000), MotionStep("idle_happy", 700)), priority=2),
    MotionSequence("reconnect", (MotionStep("attention", 700), MotionStep("greeting", 900))),
    MotionSequence("quiet-company", (MotionStep("float", 1_000), MotionStep("breathe", 900), MotionStep("idle_soft", 800))),
    MotionSequence("paper-plane", (MotionStep("paper_plane", 1_000), MotionStep("sway", 700), MotionStep("idle_happy", 700)), priority=1),
)

SEQUENCE_BY_ANIMATION = {
    "greeting": "greeting",
    "curious_peek": "hover-peek",
    "drag": "drag-landing",
    "sleepy_stretch": "sleepy-evening",
    "paper_plane": "paper-plane",
    "sparkle_happy": "celebrate",
    "thinking": "thinking",
    "rest": "quiet-company",
}
