import json

from digital_pet.preferences import DesktopPreferences, UISettingsStore


def test_ui_settings_store_falls_back_safely_for_invalid_data(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text("{not json", encoding="utf-8")

    assert store.load() == DesktopPreferences()


def test_ui_settings_store_clamps_and_persists_values(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text(json.dumps({"schema_version": 3, "pet_size": 999, "panel_opacity": 1, "always_on_top": False}), encoding="utf-8")

    loaded = store.load()
    assert loaded.pet_size == 360
    assert loaded.panel_opacity == 20
    assert not loaded.always_on_top

    saved = DesktopPreferences(pet_size=244, expanded_width=610, launch_at_login=True, close_to_tray=False, do_not_disturb=True, window_screen="DISPLAY1", window_x=20, window_y=30)
    store.save(saved)
    assert store.load() == saved


def test_v2_game_mode_state_is_migrated_back_to_the_default_topmost_setting(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text(json.dumps({"schema_version": 2, "always_on_top": False}), encoding="utf-8")

    loaded = store.load()

    assert loaded.schema_version == 3
    assert loaded.always_on_top is True
