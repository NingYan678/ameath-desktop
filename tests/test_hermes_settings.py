from pathlib import Path

import pytest

from digital_pet.hermes_settings import HermesSettingsService


def test_desktop_settings_script_compiles_before_it_can_touch_hermes(monkeypatch, tmp_path):
    service = HermesSettingsService(tmp_path, python=Path("python.exe"), source=tmp_path / "source", restart_handler=lambda: True)
    captured = {}

    def fake_run(script, *arguments):
        compile(script, "<hermes-settings>", "exec")
        captured["script"] = script
        captured["payload"] = arguments[0]
        return {"saved": True}

    monkeypatch.setattr(service, "_run_json", fake_run)
    service.apply_and_restart(model="model", provider="auto", personality="ameath", tools=["web"])

    assert '"personality": "ameath"' in captured["payload"]
    assert "ameath_desktop" in captured["script"]
    assert "for platform" not in captured["script"]


def test_apply_reports_a_restart_failure(monkeypatch, tmp_path) -> None:
    service = HermesSettingsService(tmp_path, python=Path("python.exe"), source=tmp_path / "source", restart_handler=lambda: False)
    monkeypatch.setattr(service, "_run_json", lambda *args: {"saved": True})

    with pytest.raises(RuntimeError):
        service.apply_and_restart(model="model", provider="auto", personality="none", tools=[])
