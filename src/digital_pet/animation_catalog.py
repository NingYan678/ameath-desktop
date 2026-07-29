"""Single source of truth for runtime animations and packaged sprite assets."""

from __future__ import annotations

ANIMATIONS = {
    "idle_soft": "screen3.gif", "idle_alert": "screen1.gif", "idle_happy": "sd_idle_happy.gif", "idle_sleepy": "screen6.gif",
    "move": "sd_move.gif", "drag": "sd_drag.gif", "notice": "screen1.gif", "sad": "screen2.gif",
    "attention": "screen3.gif", "thinking": "screen4.gif", "busy": "screen5.gif", "rest": "screen6.gif",
    "question": "screen7.gif", "music": "ameath.gif", "blink": "sd_blink.gif", "look_left": "sd_look_left.gif",
    "look_right": "sd_look_right.gif", "breathe": "sd_breathe.gif", "sway": "sd_sway.gif", "float": "sd_float.gif",
    "greeting": "sd_greeting.gif", "curious_peek": "sd_curious_peek.gif", "surprised": "sd_surprised.gif",
    "sleepy_stretch": "sd_sleepy_stretch.gif", "paper_plane": "sd_paper_plane.gif", "sparkle_happy": "sd_sparkle_happy.gif",
}
IDLE_ANIMATIONS = ("idle_soft", "idle_alert", "idle_happy", "idle_sleepy")
MICRO_MOTIONS = ("blink", "look_left", "look_right", "breathe", "sway", "float", "greeting", "curious_peek", "surprised", "sleepy_stretch", "paper_plane", "sparkle_happy")
HERMES_STATE_ANIMATIONS = {
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
PACKAGED_ASSET_FILES = frozenset({"gifs/ameath.ico", *(f"gifs/{filename}" for filename in ANIMATIONS.values())})
