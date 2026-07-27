import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

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


def test_shared_hermes_settings_do_not_expose_global_hermes_controls(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        DesktopPreferences(),
        UISettingsStore(tmp_path),
        FakeStartup(),
        FakeHermes(),
        lambda _: None,
        shared_hermes=True,
    )

    assert not hasattr(dialog, "model")
    assert not hasattr(dialog, "tools")


def test_backend_switch_closes_modal_before_running_the_reconfigure_callback(tmp_path):
    app = QApplication.instance() or QApplication([])
    calls = []
    dialog = SettingsDialog(
        DesktopPreferences(),
        UISettingsStore(tmp_path),
        FakeStartup(),
        FakeHermes(),
        lambda _: None,
        shared_hermes=True,
        backend_reconfigure=lambda: calls.append("reconfigure"),
    )

    dialog._reconfigure_backend()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert calls == []
    app.processEvents()
    assert calls == ["reconfigure"]


def test_isolated_hermes_settings_also_expose_backend_switching(tmp_path):
    app = QApplication.instance() or QApplication([])
    calls = []
    dialog = SettingsDialog(
        DesktopPreferences(),
        UISettingsStore(tmp_path),
        FakeStartup(),
        FakeHermes(),
        lambda _: None,
        shared_hermes=False,
        backend_reconfigure=lambda: calls.append("reconfigure"),
    )

    assert any(button.text() == "切换或重新检测 Hermes" for button in dialog.findChildren(QPushButton))
    dialog._reconfigure_backend()
    app.processEvents()
    assert calls == ["reconfigure"]
