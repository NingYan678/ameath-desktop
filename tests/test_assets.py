from digital_pet.pet_window import ANIMATION_LABELS, ANIMATIONS, IDLE_ANIMATIONS


def test_expected_recovered_animation_names_are_registered():
    assert ANIMATIONS["idle_soft"] == "idle1.gif"
    assert ANIMATIONS["drag"] == "drag.gif"
    assert ANIMATIONS["question"] == "screen7.gif"
    assert len(ANIMATIONS) == 14


def test_every_animation_has_a_display_label():
    assert set(ANIMATIONS) == set(ANIMATION_LABELS)
    assert set(IDLE_ANIMATIONS).issubset(ANIMATIONS)
