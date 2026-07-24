import json

from digital_pet.preferences import DesktopPreferences, UISettingsStore


def test_ui_settings_store_falls_back_safely_for_invalid_data(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text("{not json", encoding="utf-8")

    assert store.load() == DesktopPreferences()


def test_ui_settings_store_clamps_and_persists_values(tmp_path):
    store = UISettingsStore(tmp_path)
    store.path.write_text(json.dumps({"pet_size": 999, "panel_opacity": 1, "always_on_top": False}), encoding="utf-8")

    loaded = store.load()
    assert loaded.pet_size == 360
    assert loaded.panel_opacity == 20
    assert not loaded.always_on_top

    saved = DesktopPreferences(pet_size=244, expanded_width=610, launch_at_login=True)
    store.save(saved)
    assert store.load() == saved
