from digital_pet.animation_catalog import ANIMATIONS, HERMES_STATE_ANIMATIONS
from digital_pet.bubble_policy import BubblePriority, BubbleScheduler


def test_bubble_scheduler_suppresses_lower_priority_churn():
    scheduler = BubbleScheduler(minimum_display_ms=800)

    assert scheduler.should_show(BubblePriority.CHAT, now=1.0)
    assert not scheduler.should_show(BubblePriority.ACTIVITY, now=1.2)
    assert scheduler.should_show(BubblePriority.CONFIRMATION, now=1.2)


def test_hermes_states_point_to_registered_animations():
    assert set(HERMES_STATE_ANIMATIONS.values()).issubset(ANIMATIONS)
