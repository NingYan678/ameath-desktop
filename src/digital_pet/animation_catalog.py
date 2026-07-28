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
ANIMATION_LABELS = {
    "idle_soft": "待机：眨眼", "idle_alert": "待机：注意", "idle_happy": "待机：微笑", "idle_sleepy": "待机：困倦",
    "move": "移动过渡", "drag": "拖动反馈", "notice": "关注你", "sad": "难过", "attention": "回应你",
    "thinking": "思考", "busy": "专注", "rest": "休息", "question": "等待指令", "music": "小小音乐会",
    "blink": "眨眼", "look_left": "左顾", "look_right": "右盼", "breathe": "轻呼吸", "sway": "轻摇摆", "float": "漂浮",
    "greeting": "歪头招呼", "curious_peek": "探头", "surprised": "惊讶", "sleepy_stretch": "困倦伸展",
    "paper_plane": "纸飞机", "sparkle_happy": "闪光开心",
}
IDLE_ANIMATIONS = ("idle_soft", "idle_alert", "idle_happy", "idle_sleepy")
MICRO_MOTIONS = ("blink", "look_left", "look_right", "breathe", "sway", "float", "greeting", "curious_peek", "surprised", "sleepy_stretch", "paper_plane", "sparkle_happy")
PACKAGED_ASSET_FILES = frozenset({"gifs/ameath.ico", *(f"gifs/{filename}" for filename in ANIMATIONS.values())})
