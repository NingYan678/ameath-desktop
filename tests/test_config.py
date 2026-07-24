from pathlib import Path

import digital_pet.config as config
from digital_pet.config import Settings


def test_hermes_backend_prefers_http_when_configured(tmp_path):
    settings = Settings(tmp_path, tmp_path, "http://localhost:8000/v1", "", "model", 30, Path("missing"), Path("missing"))
    assert settings.hermes_enabled
    assert settings.hermes_backend == "http"


def test_hermes_backend_uses_local_cli_when_available(tmp_path):
    python = tmp_path / "python.exe"
    launcher = tmp_path / "hermes_launcher.py"
    python.touch()
    launcher.touch()
    settings = Settings(tmp_path, tmp_path, "", "", "model", 30, python, launcher)
    assert settings.hermes_enabled
    assert settings.hermes_backend == "cli"


def test_bridge_startup_timeout_has_a_safe_default(tmp_path):
    settings = Settings(tmp_path, tmp_path, "", "", "model", 30, Path("missing"), Path("missing"))
    assert settings.hermes_bridge_startup_seconds == 25.0


def test_packaged_copy_ignores_legacy_hermes_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "is_packaged", lambda: True)
    monkeypatch.setattr(config, "application_root", lambda: tmp_path / "install")
    monkeypatch.setattr(config, "resource_root", lambda: tmp_path / "resources")
    monkeypatch.setenv("HERMES_HOME", r"D:\hermes")
    monkeypatch.setenv("HERMES_CLI_PYTHON", r"D:\hermes\python.exe")
    monkeypatch.delenv("AMEATH_HERMES_HOME", raising=False)
    monkeypatch.delenv("AMEATH_HERMES_PYTHON", raising=False)

    settings = config.load_settings()

    assert settings.hermes_home != Path(r"D:\hermes")
    assert settings.hermes_home == settings.data_root / "hermes"
    assert settings.hermes_cli_python != Path(r"D:\hermes\python.exe")
