import json

from digital_pet.preferences import DesktopPreferences, UISettingsStore


def test_ui_settings_store_falls_back_safely_for_invalid_data(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text("{not json", encoding="utf-8")

    assert store.load() == DesktopPreferences()


def test_new_preferences_default_to_a_three_to_five_minute_companion_cadence():
    assert DesktopPreferences().proactive_max_interval_minutes == 5


def test_ui_settings_store_clamps_and_persists_values(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text(json.dumps({"schema_version": 4, "pet_size": 999, "panel_opacity": 1, "always_on_top": False, "proactive_max_interval_minutes": 500}), encoding="utf-8")

    loaded = store.load()
    assert loaded.pet_size == 360
    assert loaded.panel_opacity == 20
    assert not loaded.always_on_top
    assert loaded.proactive_max_interval_minutes == 240

    saved = DesktopPreferences(pet_size=244, expanded_width=610, launch_at_login=True, close_to_tray=False, proactive_max_interval_minutes=30, do_not_disturb=True, window_screen="DISPLAY1", window_x=20, window_y=30)
    store.save(saved)
    assert store.load() == saved


def test_v2_game_mode_state_is_migrated_back_to_the_default_topmost_setting(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text(json.dumps({"schema_version": 2, "always_on_top": False}), encoding="utf-8")

    loaded = store.load()

    assert loaded.schema_version == 7
    assert loaded.always_on_top is True


def test_v3_daily_cap_setting_migrates_to_the_new_interval_default(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text(json.dumps({"schema_version": 3, "proactive_daily_limit": 10}), encoding="utf-8")

    loaded = store.load()

    assert loaded.proactive_max_interval_minutes == 5


def test_legacy_application_update_channel_migrates_to_hermes_checks(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text(json.dumps({"schema_version": 4, "update_channel": "beta"}), encoding="utf-8")

    loaded = store.load()

    assert loaded.schema_version == 7
    assert loaded.hermes_update_checks_enabled is True
    assert not hasattr(loaded, "update_channel")
