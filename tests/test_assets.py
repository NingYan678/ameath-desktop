from PySide6.QtGui import QImageReader

from digital_pet.config import PROJECT_ROOT
from digital_pet.animation_catalog import ANIMATION_LABELS, ANIMATIONS, IDLE_ANIMATIONS, MICRO_MOTIONS


def test_expected_recovered_animation_names_are_registered():
    assert ANIMATIONS["idle_soft"] == "screen3.gif"
    assert ANIMATIONS["idle_happy"] == "sd_idle_happy.gif"
    assert ANIMATIONS["move"] == "sd_move.gif"
    assert ANIMATIONS["drag"] == "sd_drag.gif"
    assert ANIMATIONS["question"] == "screen7.gif"
    assert ANIMATIONS["music"] == "ameath.gif"
    assert len(ANIMATIONS) == 26


def test_every_animation_has_a_display_label():
    assert set(ANIMATIONS) == set(ANIMATION_LABELS)
    assert set(IDLE_ANIMATIONS).issubset(ANIMATIONS)


def test_new_micro_motion_gifs_are_uniform_animation_assets():
    expected = {"blink", "look_left", "look_right", "breathe", "sway", "float", "greeting", "curious_peek", "surprised", "sleepy_stretch", "paper_plane", "sparkle_happy"}
    assert set(MICRO_MOTIONS) == expected
    for name in expected:
        reader = QImageReader(str(PROJECT_ROOT / "assets" / "recovered" / "gifs" / ANIMATIONS[name]))
        assert reader.canRead(), name
        assert reader.size().width() == 200 and reader.size().height() == 200
        assert reader.supportsAnimation() and reader.imageCount() >= 8
        image = reader.read()
        assert image.hasAlphaChannel()
        assert image.pixelColor(0, 0).alpha() == 0
