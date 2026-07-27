from datetime import datetime, timedelta
import random

from digital_pet.pet_state import PROACTIVE_EVENTS, PetStateEngine, PetStateStore
from digital_pet.preferences import DesktopPreferences


def test_familiarity_only_grows_and_persists(tmp_path):
    engine = PetStateEngine(PetStateStore(tmp_path), DesktopPreferences())
    now = datetime(2026, 7, 27, 12, 0)

    engine.record_interaction(now)
    engine.record_interaction(now + timedelta(days=30))

    assert engine.state.familiarity == 2
    assert PetStateStore(tmp_path).load().familiarity == 2


def test_proactive_delay_stays_within_the_user_selected_ceiling(tmp_path):
    preferences = DesktopPreferences(proactive_max_interval_minutes=45)
    engine = PetStateEngine(PetStateStore(tmp_path), preferences, rng=random.Random(7))

    delays = [engine.proactive_delay_ms() for _ in range(20)]

    assert all(45 * 60_000 * 0.6 <= delay <= 45 * 60_000 for delay in delays)
    assert len(set(delays)) > 1


def test_proactive_has_no_daily_cap_and_remembers_recent_events(tmp_path):
    engine = PetStateEngine(PetStateStore(tmp_path), DesktopPreferences(), rng=random.Random(11))
    now = datetime(2026, 7, 27, 12, 0)
    events = []
    for index in range(20):
        event = engine.proactive_event(fullscreen=False, busy=False, now=now + timedelta(minutes=index))
        assert event is not None
        events.append(event)

    assert len(events) == 20
    assert len({event.event_id for event in events[:12]}) == 12
    assert all(left.category != right.category for left, right in zip(events, events[1:]))
    assert PetStateStore(tmp_path).load().recent_proactive_ids == tuple(event.event_id for event in events[-12:])


def test_proactive_respects_quiet_hours_and_protected_states(tmp_path):
    moment = datetime(2026, 7, 27, 10, 0)
    for preferences, fullscreen, busy, instant in (
        (DesktopPreferences(), True, False, moment),
        (DesktopPreferences(), False, True, moment),
        (DesktopPreferences(do_not_disturb=True), False, False, moment),
        (DesktopPreferences(quiet_start_hour=23, quiet_end_hour=8), False, False, datetime(2026, 7, 27, 23, 30)),
    ):
        engine = PetStateEngine(PetStateStore(tmp_path / str(fullscreen) / str(busy) / str(preferences.do_not_disturb) / instant.strftime("%H")), preferences)
        assert engine.proactive_event(fullscreen=fullscreen, busy=busy, now=instant) is None


def test_manual_proactive_event_overrides_automatic_quiet_and_dnd_limits(tmp_path):
    engine = PetStateEngine(PetStateStore(tmp_path), DesktopPreferences(do_not_disturb=True))

    assert engine.proactive_event(fullscreen=True, busy=True, now=datetime(2026, 7, 27, 23, 30), manual=True)


def test_proactive_catalogue_is_original_and_balanced_for_reply_invites():
    forbidden = ("主人", "老公", "老婆", "亲爱的")
    assert len(PROACTIVE_EVENTS) == 40
    assert len({event.event_id for event in PROACTIVE_EVENTS}) == len(PROACTIVE_EVENTS)
    assert sum(event.expects_reply for event in PROACTIVE_EVENTS) == 10
    assert all(not any(word in event.text for word in forbidden) for event in PROACTIVE_EVENTS)
