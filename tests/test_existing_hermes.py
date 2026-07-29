import json
from pathlib import Path

import pytest

from digital_pet.config import Settings
from digital_pet.existing_hermes import (
    BackendSelectionStore,
    ExistingHermesRuntimeService,
    HermesInstallation,
    ProbeStatus,
    _candidate_homes,
    probe_hermes_home,
    inspect_hermes_home,
)
from digital_pet.runtime_descriptor import RuntimeHealth


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        asset_root=tmp_path / "assets",
        data_root=tmp_path / "ameath-data",
        hermes_cli_python=tmp_path / "runtime" / "python.exe",
        hermes_cli_launcher=tmp_path / "runtime" / "hermes_cli" / "main.py",
        install_root=tmp_path / "app",
    )


def make_installation(tmp_path: Path, *, desktop_enabled: bool = False) -> HermesInstallation:
    home = tmp_path / "legacy"
    source = home / "hermes-agent"
    python = source / "venv" / "Scripts" / "python.exe"
    launcher = source / "hermes_cli" / "main.py"
    python.parent.mkdir(parents=True)
    launcher.parent.mkdir(parents=True)
    python.touch()
    launcher.touch()
    (home / "config.yaml").write_text("model: {}\n", encoding="utf-8")
    return HermesInstallation(home, python, launcher, source, "1:2", desktop_enabled)


def test_selection_store_keeps_only_non_secret_backend_metadata(tmp_path):
    installation = make_installation(tmp_path)
    store = BackendSelectionStore(tmp_path / "ameath-data")

    store.save("shared", installation)

    assert store.load() == ("shared", installation.home, "1:2")
    assert set(json.loads(store.path.read_text(encoding="utf-8"))) == {"mode", "home", "fingerprint"}


def test_discovery_uses_environment_home_before_default(monkeypatch, tmp_path):
    selected = tmp_path / "custom-hermes"
    monkeypatch.setenv("HERMES_HOME", str(selected))

    assert _candidate_homes()[0] == selected
    assert Path(r"D:\hermes") in _candidate_homes()


def test_inspect_requires_all_runtime_files_and_uses_safe_config_check(monkeypatch, tmp_path):
    installation = make_installation(tmp_path, desktop_enabled=True)
    monkeypatch.setattr("digital_pet.existing_hermes._inspect_config", lambda *_: True)

    detected = inspect_hermes_home(installation.home)

    assert detected is not None
    assert detected.home == installation.home
    assert detected.desktop_enabled is True


def test_shared_prepare_backs_up_and_enables_plugin_only_after_selection(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    plugin = settings.install_root / "hermes_platform" / "ameath_desktop"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: ameath-desktop\n", encoding="utf-8")
    (plugin / "adapter.py").write_text("adapter", encoding="utf-8")
    installation = make_installation(tmp_path)
    runtime = ExistingHermesRuntimeService(settings, installation)
    calls = []
    monkeypatch.setattr("digital_pet.existing_hermes._compatible", lambda *_: True)
    monkeypatch.setattr(runtime, "_enable_desktop_plugin", lambda: calls.append("enabled"))
    monkeypatch.setattr(runtime, "quick_health", lambda: RuntimeHealth.STOPPED)

    result = runtime.prepare()

    assert result.changed is True
    assert calls == ["enabled"]
    assert (installation.home / "config.yaml.ameath-backup").is_file()
    assert (installation.home / "plugins" / "platforms" / "ameath_desktop" / "plugin.yaml").is_file()


def test_shared_runtime_does_not_start_a_second_gateway_when_one_is_running(monkeypatch, tmp_path):
    runtime = ExistingHermesRuntimeService(make_settings(tmp_path), make_installation(tmp_path, desktop_enabled=True))
    monkeypatch.setattr(runtime, "quick_health", lambda: RuntimeHealth.VERIFYING)

    assert runtime.start_gateway() is False


def test_failed_plugin_activation_rolls_back_config_and_new_plugin(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    plugin = settings.install_root / "hermes_platform" / "ameath_desktop"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: ameath-desktop\n", encoding="utf-8")
    (plugin / "adapter.py").write_text("adapter", encoding="utf-8")
    installation = make_installation(tmp_path)
    original = (installation.home / "config.yaml").read_text(encoding="utf-8")
    runtime = ExistingHermesRuntimeService(settings, installation)
    monkeypatch.setattr("digital_pet.existing_hermes._compatible", lambda *_: True)
    monkeypatch.setattr(runtime, "_enable_desktop_plugin", lambda: (_ for _ in ()).throw(RuntimeError("write failed")))

    with pytest.raises(RuntimeError, match="write failed"):
        runtime.prepare()

    assert (installation.home / "config.yaml").read_text(encoding="utf-8") == original
    assert not (installation.home / "plugins" / "platforms" / "ameath_desktop").exists()


def test_failed_plugin_update_restores_an_existing_plugin(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    plugin = settings.install_root / "hermes_platform" / "ameath_desktop"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: ameath-desktop\n", encoding="utf-8")
    (plugin / "adapter.py").write_text("new", encoding="utf-8")
    installation = make_installation(tmp_path)
    existing = installation.home / "plugins" / "platforms" / "ameath_desktop"
    existing.mkdir(parents=True)
    (existing / "adapter.py").write_text("old", encoding="utf-8")
    runtime = ExistingHermesRuntimeService(settings, installation)
    monkeypatch.setattr("digital_pet.existing_hermes._compatible", lambda *_: True)
    monkeypatch.setattr(runtime, "_enable_desktop_plugin", lambda: (_ for _ in ()).throw(RuntimeError("write failed")))

    with pytest.raises(RuntimeError):
        runtime.prepare()

    assert (existing / "adapter.py").read_text(encoding="utf-8") == "old"


def test_shared_plugin_update_removes_files_retired_from_the_source(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    plugin = settings.install_root / "hermes_platform" / "ameath_desktop"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: ameath-desktop\n", encoding="utf-8")
    (plugin / "adapter.py").write_text("new", encoding="utf-8")
    installation = make_installation(tmp_path, desktop_enabled=True)
    existing = installation.home / "plugins" / "platforms" / "ameath_desktop"
    existing.mkdir(parents=True)
    (existing / "plugin.yaml").write_text("name: ameath-desktop\n", encoding="utf-8")
    (existing / "adapter.py").write_text("old", encoding="utf-8")
    (existing / "retired.py").write_text("old code", encoding="utf-8")
    runtime = ExistingHermesRuntimeService(settings, installation)
    monkeypatch.setattr("digital_pet.existing_hermes._compatible", lambda *_: True)
    monkeypatch.setattr(runtime, "quick_health", lambda: RuntimeHealth.STOPPED)

    runtime.prepare()

    assert (existing / "adapter.py").read_text(encoding="utf-8") == "new"
    assert not (existing / "retired.py").exists()


def test_probe_reports_invalid_yaml_without_trying_to_modify_hermes(monkeypatch, tmp_path):
    installation = make_installation(tmp_path)
    monkeypatch.setattr("digital_pet.existing_hermes._inspect_config", lambda *_: None)

    probe = probe_hermes_home(installation.home)

    assert probe.status is ProbeStatus.INVALID_CONFIG
    assert probe.installation is None


def test_runtime_descriptor_requires_a_verified_pid(monkeypatch, tmp_path):
    runtime = ExistingHermesRuntimeService(make_settings(tmp_path), make_installation(tmp_path, desktop_enabled=True))
    runtime.settings.desktop_runtime_path.write_text('{"state":"ready","port":1234,"token":"x"}', encoding="utf-8")

    assert not runtime.is_gateway_ready()

    runtime.settings.desktop_runtime_path.write_text('{"state":"ready","port":1234,"token":"xxxxxxxxxxxxxxxxxxxxxxxx","pid":123}', encoding="utf-8")
    monkeypatch.setattr("digital_pet.runtime_descriptor.pid_is_alive", lambda pid: pid == 123)
    monkeypatch.setattr("digital_pet.existing_hermes.pid_belongs_to_runtime", lambda pid, source: pid == 123)
    assert runtime.verify_identity() is RuntimeHealth.READY
    assert runtime.is_gateway_ready()
