import json
from pathlib import Path

from digital_pet.ameath_runtime import AmeathRuntimeService, ModelProfile
from digital_pet.config import Settings
from digital_pet.onboarding import OnboardingDialog


class FakeCredentials:
    def __init__(self):
        self.saved = None

    def save(self, provider, key):
        self.saved = (provider, key)

    def load(self):
        return self.saved

    def load_with_status(self):
        return (self.saved, "available" if self.saved else "missing")

    def clear(self):
        self.saved = None


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        asset_root=tmp_path / "assets",
        data_root=tmp_path / "data",
        hermes_base_url="",
        hermes_api_key="",
        hermes_model="",
        hermes_timeout_seconds=30,
        hermes_cli_python=tmp_path / "runtime" / "python" / "python.exe",
        hermes_cli_launcher=tmp_path / "runtime" / "hermes-agent" / "hermes_cli" / "main.py",
        hermes_home=tmp_path / "data" / "hermes",
        install_root=tmp_path,
        hermes_runtime_root=tmp_path / "runtime",
    )


def test_profile_writes_a_clean_isolated_hermes_home(tmp_path):
    settings = make_settings(tmp_path)
    plugin = settings.install_root / "hermes_platform" / "ameath_desktop"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: ameath-desktop\n", encoding="utf-8")
    runtime = AmeathRuntimeService(settings)
    runtime.credentials = FakeCredentials()

    runtime.save_profile(ModelProfile("deepseek", "deepseek-chat", "https://api.deepseek.com/v1", "secret-key"))

    config = json.loads((settings.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    assert config["agent"]["personalities"]["ameath"]
    assert config["platforms"]["ameath_desktop"]["enabled"]
    assert "secret-key" not in (settings.hermes_home / "config.yaml").read_text(encoding="utf-8")
    assert runtime.credentials.saved == ("deepseek", "secret-key")
    assert (settings.hermes_home / "plugins" / "platforms" / "ameath_desktop" / "plugin.yaml").is_file()


def test_onboarding_rejects_missing_required_model_fields():
    ok, message = OnboardingDialog.test_profile(ModelProfile("openai", "", "https://api.openai.com/v1", "key"))
    assert not ok
    assert message


def test_prepare_restores_a_missing_config_from_the_public_profile(tmp_path):
    settings = make_settings(tmp_path)
    runtime = AmeathRuntimeService(settings)
    runtime.credentials = FakeCredentials()
    runtime.save_profile(ModelProfile("deepseek", "deepseek-chat", "https://api.deepseek.com/v1", "secret-key"))
    (settings.hermes_home / "config.yaml").unlink()

    runtime.prepare()

    assert runtime.configured
    assert json.loads((settings.hermes_home / "config.yaml").read_text(encoding="utf-8"))["model"]["default"] == "deepseek-chat"


def test_prepare_restores_a_missing_profile_from_its_public_backup(tmp_path):
    settings = make_settings(tmp_path)
    runtime = AmeathRuntimeService(settings)
    runtime.credentials = FakeCredentials()
    runtime.save_profile(ModelProfile("deepseek", "deepseek-chat", "https://api.deepseek.com/v1", "secret-key"))
    (settings.hermes_home / "model_profile.json").unlink()

    runtime.prepare()

    assert runtime.configured
    assert (settings.hermes_home / "model_profile.json").is_file()


def test_prepare_replaces_an_invalid_derived_config(tmp_path):
    settings = make_settings(tmp_path)
    runtime = AmeathRuntimeService(settings)
    runtime.credentials = FakeCredentials()
    runtime.save_profile(ModelProfile("deepseek", "deepseek-chat", "https://api.deepseek.com/v1", "secret-key"))
    (settings.hermes_home / "config.yaml").write_text("not valid JSON", encoding="utf-8")

    runtime.prepare()

    assert runtime.configured
