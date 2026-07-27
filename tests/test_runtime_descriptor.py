import json
from pathlib import Path
from types import SimpleNamespace

from digital_pet.runtime_descriptor import (
    RuntimeHealth,
    pid_belongs_to_runtime,
    quick_runtime_health,
    read_runtime_descriptor,
    read_verified_runtime,
    stop_verified_runtime,
)


def write_descriptor(path, **overrides):
    payload = {"state": "ready", "port": 4321, "token": "x" * 24, "pid": 123}
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_runtime_descriptor_validates_all_connection_fields(tmp_path):
    path = tmp_path / "runtime.json"
    write_descriptor(path)
    assert read_runtime_descriptor(path).port == 4321

    write_descriptor(path, token="short")
    assert read_runtime_descriptor(path) is None
    write_descriptor(path, port=70_000)
    assert read_runtime_descriptor(path) is None
    write_descriptor(path, pid=0)
    assert read_runtime_descriptor(path) is None


def test_verified_runtime_requires_command_ownership(monkeypatch, tmp_path):
    path = tmp_path / "runtime.json"
    write_descriptor(path)
    monkeypatch.setattr("digital_pet.runtime_descriptor.pid_is_alive", lambda pid: True)
    monkeypatch.setattr("digital_pet.runtime_descriptor.pid_belongs_to_runtime", lambda pid, source: False)
    assert read_verified_runtime(path, tmp_path / "hermes") is None


def test_gateway_identity_uses_one_hidden_parent_chain_query(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="true\n", returncode=0)

    monkeypatch.setattr("digital_pet.runtime_descriptor.subprocess.run", fake_run)
    assert pid_belongs_to_runtime(123, Path(r"D:\hermes\hermes-agent"))
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:5] == ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
    assert "for ($step" in command[-1]
    assert kwargs["creationflags"]


def test_gateway_identity_rejects_an_unrelated_parent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "digital_pet.runtime_descriptor.subprocess.run",
        lambda command, **kwargs: SimpleNamespace(stdout="false\n", returncode=0),
    )
    assert not pid_belongs_to_runtime(123, tmp_path / "hermes")


def test_quick_health_never_spawns_a_subprocess(monkeypatch, tmp_path):
    path = tmp_path / "runtime.json"
    write_descriptor(path)
    monkeypatch.setattr("digital_pet.runtime_descriptor.pid_is_alive", lambda pid: True)
    monkeypatch.setattr(
        "digital_pet.runtime_descriptor.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected process")),
    )
    health, fingerprint = quick_runtime_health(path, tmp_path / "hermes", None)
    assert health is RuntimeHealth.VERIFYING
    assert fingerprint is not None


def test_stop_targets_only_the_verified_descriptor_pid(monkeypatch, tmp_path):
    path = tmp_path / "runtime.json"
    write_descriptor(path, pid=987)
    monkeypatch.setattr("digital_pet.runtime_descriptor.pid_is_alive", lambda pid: True)
    monkeypatch.setattr("digital_pet.runtime_descriptor.pid_belongs_to_runtime", lambda pid, source: True)
    calls = []
    monkeypatch.setattr(
        "digital_pet.runtime_descriptor.subprocess.run",
        lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0),
    )

    assert stop_verified_runtime(path, tmp_path / "hermes")
    assert calls == [["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "Stop-Process -Id 987 -Force"]]
