import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from digital_pet.hermes_settings import HermesSettingsSnapshot
from digital_pet.preferences import DesktopPreferences, UISettingsStore
from digital_pet.settings_dialog import SettingsDialog


class FakeStartup:
    def is_enabled(self):
        return False

    def set_enabled(self, enabled):
        self.enabled = enabled


class FakeHermes:
    def read(self):
        return HermesSettingsSnapshot("model-a", "auto", "ameath", ("ameath", "helpful"), ("browser", "web"), True)

    def apply_and_restart(self, **kwargs):
        self.applied = kwargs


def test_settings_dialog_previews_and_cancels_back_to_initial_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    initial = DesktopPreferences(pet_size=210)
    previewed = []
    dialog = SettingsDialog(initial, UISettingsStore(tmp_path), FakeStartup(), FakeHermes(), previewed.append)

    dialog.pet_size.set_value(260)
    assert previewed[-1].pet_size == 260
    dialog.reject()
    assert previewed[-1] == initial


def test_settings_dialog_saves_preferences_and_stages_global_hermes_update(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    startup = FakeStartup()
    hermes = FakeHermes()
    store = UISettingsStore(tmp_path)
    dialog = SettingsDialog(DesktopPreferences(), store, startup, hermes, lambda _: None)
    dialog.pet_size.set_value(250)
    dialog.personality.setCurrentText("helpful")
    monkeypatch.setattr("digital_pet.settings_dialog.QMessageBox.information", lambda *args: None)

    dialog._apply_hermes()

    assert store.load().pet_size == 250
    assert startup.enabled is False
    assert hermes.applied["personality"] == "helpful"
    assert "browser" in hermes.applied["tools"]


def test_settings_dialog_can_save_desktop_without_restarting_hermes(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    hermes = FakeHermes()
    store = UISettingsStore(tmp_path)
    dialog = SettingsDialog(DesktopPreferences(), store, FakeStartup(), hermes, lambda _: None)
    dialog.opacity.set_value(35)
    monkeypatch.setattr("digital_pet.settings_dialog.QMessageBox.information", lambda *args: None)

    dialog._save_desktop()

    assert store.load().panel_opacity == 35
    assert not hasattr(hermes, "applied")
