from pathlib import Path

import digital_pet.config as config
from digital_pet.config import Settings


def test_packaged_copy_ignores_development_hermes_environment(monkeypatch, tmp_path):
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


def test_development_startup_uses_the_hidden_vbs_launcher(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "is_packaged", lambda: False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    settings = Settings(tmp_path, tmp_path, Path("missing"), Path("missing"))

    assert settings.launch_command == f'wscript.exe //B "{tmp_path / "run.vbs"}"'
