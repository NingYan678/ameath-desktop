from pathlib import Path

from digital_pet.hermes_settings import HermesSettingsService


def test_global_settings_script_compiles_before_it_can_touch_hermes(monkeypatch, tmp_path):
    service = HermesSettingsService(tmp_path, python=Path("python.exe"))
    captured = {}

    def fake_run(script, *arguments):
        compile(script, "<hermes-settings>", "exec")
        captured["payload"] = arguments[0]
        return {"saved": True}

    monkeypatch.setattr(service, "_run_json", fake_run)
    monkeypatch.setattr(service, "restart_gateway", lambda: None)

    service.apply_and_restart(model="model", provider="auto", personality="ameath", tools=["web"])

    assert '"personality": "ameath"' in captured["payload"]
