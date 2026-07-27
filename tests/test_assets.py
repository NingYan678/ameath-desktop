from digital_pet.pet_window import ANIMATION_LABELS, ANIMATIONS, IDLE_ANIMATIONS


def test_expected_recovered_animation_names_are_registered():
    assert ANIMATIONS["idle_soft"] == "screen3.gif"
    assert ANIMATIONS["idle_happy"] == "sd_idle_happy.gif"
    assert ANIMATIONS["move"] == "sd_move.gif"
    assert ANIMATIONS["drag"] == "sd_drag.gif"
    assert ANIMATIONS["question"] == "screen7.gif"
    assert ANIMATIONS["music"] == "ameath.gif"
    assert len(ANIMATIONS) == 14


def test_every_animation_has_a_display_label():
    assert set(ANIMATIONS) == set(ANIMATION_LABELS)
    assert set(IDLE_ANIMATIONS).issubset(ANIMATIONS)
