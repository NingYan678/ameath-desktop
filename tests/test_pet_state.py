from datetime import datetime, timedelta

from digital_pet.pet_state import PetStateEngine, PetStateStore
from digital_pet.preferences import DesktopPreferences


def test_familiarity_only_grows_and_persists(tmp_path):
    engine = PetStateEngine(PetStateStore(tmp_path), DesktopPreferences())
    now = datetime(2026, 7, 27, 12, 0)

    engine.record_interaction(now)
    engine.record_interaction(now + timedelta(days=30))

    assert engine.state.familiarity == 2
    assert PetStateStore(tmp_path).load().familiarity == 2


def test_proactive_respects_quiet_hours_spacing_and_daily_cap(tmp_path):
    prefs = DesktopPreferences(proactive_daily_limit=1, quiet_start_hour=23, quiet_end_hour=8)
    engine = PetStateEngine(PetStateStore(tmp_path), prefs)

    assert engine.proactive_message(fullscreen=False, busy=False, now=datetime(2026, 7, 27, 23, 30)) is None
    first = engine.proactive_message(fullscreen=False, busy=False, now=datetime(2026, 7, 27, 10, 0))
    assert first
    assert engine.proactive_message(fullscreen=False, busy=False, now=datetime(2026, 7, 27, 12, 0)) is None
    assert engine.proactive_message(fullscreen=False, busy=False, now=datetime(2026, 7, 28, 10, 0))


def test_proactive_is_silent_for_fullscreen_busy_or_dnd(tmp_path):
    moment = datetime(2026, 7, 27, 10, 0)
    for preferences, fullscreen, busy in (
        (DesktopPreferences(), True, False),
        (DesktopPreferences(), False, True),
        (DesktopPreferences(do_not_disturb=True), False, False),
    ):
        engine = PetStateEngine(PetStateStore(tmp_path / str(fullscreen) / str(busy) / str(preferences.do_not_disturb)), preferences)
        assert engine.proactive_message(fullscreen=fullscreen, busy=busy, now=moment) is None
