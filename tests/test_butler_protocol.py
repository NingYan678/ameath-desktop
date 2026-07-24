from datetime import datetime

from digital_pet.butler_protocol import BubblePriority, BubbleScheduler, PET_STATE_ANIMATIONS, parse_butler_reply


def test_structured_reply_parses_a_reminder_proposal():
    reply = parse_butler_reply(
        '{"reply":"我可以帮你记下。","state":"permission","proposal":'
        '{"action":"create_reminder","title":"开会","due_at":"2026-07-25 09:00"}}'
    )

    assert reply.structured
    assert reply.state == "permission"
    assert reply.proposal is not None
    assert reply.proposal.action == "create_reminder"
    assert reply.proposal.due_at == datetime(2026, 7, 25, 9, 0)


def test_plain_text_reply_falls_back_safely():
    reply = parse_butler_reply("普通回复")

    assert reply.reply == "普通回复"
    assert reply.proposal is None
    assert reply.state == "attention"


def test_invalid_proposal_is_ignored_but_visible_reply_survives():
    reply = parse_butler_reply(
        '{"reply":"需要你确认。","state":"permission","proposal":'
        '{"action":"cancel_reminder","task_id":""}}'
    )

    assert reply.structured
    assert reply.proposal is None


def test_high_priority_bubble_interrupts_low_priority_lock():
    scheduler = BubbleScheduler(minimum_display_ms=800)

    assert scheduler.should_show(BubblePriority.CHAT, now=1.0)
    assert not scheduler.should_show(BubblePriority.ACTIVITY, now=1.2)
    assert scheduler.should_show(BubblePriority.CONFIRMATION, now=1.2)


def test_every_butler_state_has_an_existing_animation():
    assert set(PET_STATE_ANIMATIONS.values()).issubset(
        {"thinking", "busy", "attention", "question", "music", "sad", "idle_soft"}
    )
