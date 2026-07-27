import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication

from digital_pet.config import Settings
from digital_pet.pet_window import PetWindow


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        asset_root=tmp_path / "assets",
        data_root=tmp_path / "data",
        hermes_base_url="",
        hermes_api_key="",
        hermes_model="",
        hermes_timeout_seconds=30,
        hermes_cli_python=tmp_path / "runtime" / "python.exe",
        hermes_cli_launcher=tmp_path / "runtime" / "hermes_cli.py",
        hermes_home=tmp_path / "data" / "hermes",
        install_root=tmp_path,
    )


def test_manual_game_mode_keeps_a_visible_window_and_preserves_topmost_preference(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = PetWindow(make_settings(tmp_path))
    window.show()
    app.processEvents()
    original_topmost = window.preferences.always_on_top

    window.toggle_game_mode()
    app.processEvents()

    assert window.isVisible()
    assert window.game_mode_active
    assert window.preferences.always_on_top is original_topmost

    window.toggle_game_mode()
    app.processEvents()
    assert window.isVisible()
    assert not window.game_mode_active
    window.close()


def test_toggle_proactive_persists_and_emits_current_state(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = PetWindow(make_settings(tmp_path))
    states: list[bool] = []
    window.proactive_changed.connect(states.append)

    original = window.preferences.proactive_enabled
    window.toggle_proactive()
    app.processEvents()

    assert window.preferences.proactive_enabled is not original
    assert states == [not original]
    window.close()
