from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from digital_pet.config import Settings, active_runtime_root
from digital_pet.hermes_update import (
    OFFICIAL_REPOSITORY,
    HermesUpdateInfo,
    HermesUpdateService,
    HermesUpdateState,
    HermesUpdateStateStore,
)
from digital_pet.runtime_descriptor import RuntimeHealth


OLD = "1" * 40
NEW = "2" * 40


def make_settings(tmp_path: Path) -> Settings:
    runtime = tmp_path / "runtime"
    source = runtime / "hermes-agent"
    python = source / "venv" / "Scripts" / "python.exe"
    launcher = source / "hermes_cli" / "main.py"
    python.parent.mkdir(parents=True)
    launcher.parent.mkdir(parents=True)
    python.touch()
    launcher.touch()
    (source / ".git").mkdir()
    return Settings(
        asset_root=tmp_path / "assets",
        data_root=tmp_path / "data",
        hermes_cli_python=python,
        hermes_cli_launcher=launcher,
        hermes_home=tmp_path / "home",
        install_root=tmp_path,
        hermes_runtime_root=runtime,
    )


class CommandRunner:
    def __init__(self, *, dirty: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.dirty = dirty
        self.updated = False

    def __call__(self, command, **kwargs):
        command = [str(item) for item in command]
        self.calls.append(command)
        joined = " ".join(command)
        if "ls-remote" in command:
            stdout = f"{NEW}\trefs/heads/main\n"
        elif "remote get-url origin" in joined:
            stdout = OFFICIAL_REPOSITORY + "\n"
        elif "status --porcelain" in joined:
            stdout = " M local.py\n" if self.dirty else ""
        elif "branch --show-current" in joined:
            stdout = "codex/local-experiment\n"
        elif "rev-parse HEAD" in joined:
            stdout = (NEW if self.updated else OLD) + "\n"
        elif " update " in f" {joined} ":
            self.updated = True
            stdout = "updated\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout, "")


def test_shared_update_uses_official_command_without_force_flags(tmp_path):
    settings = make_settings(tmp_path)
    runner = CommandRunner()
    service = HermesUpdateService(settings, shared=True, run_command=runner)

    result = service.apply(object())  # shared updates never manipulate the isolated runtime object

    update = next(call for call in runner.calls if "update" in call)
    assert update[-5:] == [
        str(settings.hermes_cli_launcher),
        "update",
        "--yes",
        "--branch",
        "main",
    ]
    assert not any(item.startswith("--force") for item in update)
    assert result.previous_revision == OLD
    assert result.current_revision == NEW


def test_shared_update_refuses_a_dirty_worktree(tmp_path):
    settings = make_settings(tmp_path)
    runner = CommandRunner(dirty=True)
    service = HermesUpdateService(settings, shared=True, run_command=runner)

    with pytest.raises(RuntimeError, match="未提交修改"):
        service.apply(object())

    assert not any("update" in call for call in runner.calls)


def test_update_state_uses_daily_checks_and_six_hour_retry(tmp_path):
    store = HermesUpdateStateStore(tmp_path)
    now = datetime.now(timezone.utc)
    store.save(HermesUpdateState(last_checked_at=(now - timedelta(hours=23)).isoformat()))
    assert not store.check_due(now)
    store.save(HermesUpdateState(last_checked_at=now.isoformat(), retry_after=(now + timedelta(hours=5)).isoformat()))
    assert not store.check_due(now)
    assert store.check_due(now + timedelta(hours=6))


class FakeRuntime:
    def __init__(self, settings: Settings, *, ready: bool = True) -> None:
        self.settings = settings
        self.ready = ready
        self.roots: list[Path] = []
        self.stop_calls = 0
        self.start_calls = 0

    def stop_gateway(self) -> bool:
        self.stop_calls += 1
        return True

    def switch_runtime(self, root: Path) -> None:
        self.roots.append(root)
        self.settings = Settings(
            self.settings.asset_root,
            self.settings.data_root,
            root / "python.exe",
            root / "hermes-agent" / "hermes_cli" / "main.py",
            self.settings.hermes_home,
            self.settings.install_root,
            root,
        )

    def prepare(self) -> None:
        return None

    def start_gateway(self) -> bool:
        self.start_calls += 1
        return True

    def verify_identity(self) -> RuntimeHealth:
        return RuntimeHealth.READY if self.ready else RuntimeHealth.STOPPED


def test_isolated_update_switches_pointer_only_after_gateway_validation(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    slot = settings.data_root / "runtimes" / NEW
    slot.mkdir(parents=True)
    runtime = FakeRuntime(settings)
    service = HermesUpdateService(settings, shared=False)
    monkeypatch.setattr(service, "_prepare_slot", lambda *args: slot)
    monkeypatch.setattr(service, "_retain_runtime_slots", lambda *args: None)
    info = HermesUpdateInfo(OLD, NEW, OFFICIAL_REPOSITORY, "isolated", True, "")

    result = service._apply_isolated(info, tmp_path / "update.log", runtime)

    pointer = json.loads((settings.data_root / "runtime_current.json").read_text(encoding="utf-8"))
    assert pointer == {"hermes_commit": NEW}
    assert runtime.roots == [slot]
    assert runtime.stop_calls == 1
    assert result.runtime_root == slot


def test_isolated_update_rolls_back_without_changing_pointer(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    slot = settings.data_root / "runtimes" / NEW
    slot.mkdir(parents=True)
    runtime = FakeRuntime(settings, ready=False)
    service = HermesUpdateService(settings, shared=False)
    monkeypatch.setattr(service, "_prepare_slot", lambda *args: slot)
    monkeypatch.setattr(service, "_wait_until_ready", lambda *args: False)
    info = HermesUpdateInfo(OLD, NEW, OFFICIAL_REPOSITORY, "isolated", True, "")

    with pytest.raises(RuntimeError, match="启动验证"):
        service._apply_isolated(info, tmp_path / "update.log", runtime)

    assert not (settings.data_root / "runtime_current.json").exists()
    assert runtime.roots[-1] == settings.hermes_runtime_root
    assert runtime.stop_calls == 2


def test_packaged_runtime_pointer_is_confined_and_falls_back_to_baseline(tmp_path):
    install = tmp_path / "install"
    data = tmp_path / "data"
    bundled = install / "runtime"
    bundled.mkdir(parents=True)
    slot = data / "runtimes" / NEW
    interpreter = slot / "python" / "cpython" / "python.exe"
    launcher = slot / "hermes-agent" / "hermes_cli" / "main.py"
    interpreter.parent.mkdir(parents=True)
    launcher.parent.mkdir(parents=True)
    interpreter.touch()
    launcher.touch()
    (slot / "runtime_metadata.json").write_text(
        json.dumps({"hermes_commit": NEW, "python_relative_path": "python/cpython/python.exe"}),
        encoding="utf-8",
    )
    data.mkdir(exist_ok=True)
    (data / "runtime_current.json").write_text(json.dumps({"hermes_commit": NEW}), encoding="utf-8")

    assert active_runtime_root(install, data) == slot.resolve()

    (data / "runtime_current.json").write_text(
        json.dumps({"hermes_commit": "../../outside"}),
        encoding="utf-8",
    )
    assert active_runtime_root(install, data) == bundled
