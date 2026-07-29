import json

from digital_pet.maintenance import reset_user_data


def test_shared_reset_removes_only_ameath_data(monkeypatch, tmp_path):
    data = tmp_path / "Ameath"
    data.mkdir()
    (data / "runtime_backend.json").write_text(json.dumps({"mode": "shared", "home": r"D:\hermes"}), encoding="utf-8")
    (data / "ui_settings.json").write_text("{}", encoding="utf-8")
    stopped = []
    monkeypatch.setattr("digital_pet.maintenance.stop_verified_runtime", lambda *args: stopped.append(args) or True)

    assert reset_user_data(data, tmp_path / "Programs" / "Ameath")
    assert not data.exists()
    assert stopped == []


def test_invalid_isolated_descriptor_preserves_user_data(tmp_path):
    data = tmp_path / "Ameath"
    runtime = data / "hermes" / "ameath_desktop_runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text('{"state":"ready","pid":42}', encoding="utf-8")

    assert not reset_user_data(data, tmp_path / "Programs" / "Ameath")
    assert data.exists()


def test_verified_isolated_gateway_is_stopped_before_reset(monkeypatch, tmp_path):
    data = tmp_path / "Ameath"
    runtime = data / "hermes" / "ameath_desktop_runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps({"state": "ready", "port": 1234, "token": "x" * 24, "pid": 42}), encoding="utf-8")
    stopped = []
    monkeypatch.setattr("digital_pet.maintenance.stop_verified_runtime", lambda path, source: stopped.append((path, source)) or True)

    install = tmp_path / "Programs" / "Ameath"
    assert reset_user_data(data, install)
    assert stopped == [(runtime, install / "runtime" / "hermes-agent")]
