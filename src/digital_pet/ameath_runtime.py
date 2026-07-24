"""Own and start the isolated Hermes runtime shipped with Ameath."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, is_packaged
from .credentials import CredentialStore


AMEATH_PERSONALITY = """You are 爱弥斯（Ameath）, the user's capable and warm personal AI butler.

Speak primarily in natural Chinese unless the user uses another language. Be calm,
observant, concise, and dependable: acknowledge the user's intent, give the useful
result first, and explain only the details that help them act. Show gentle warmth
and quiet personality, but never use excessive cute filler, roleplay, or decorative
symbols that reduce clarity.

Treat every connected Hermes channel as an extension of the same assistant. Use
Hermes's native memory, skills, tools, task system, and permission flow when useful.
Never pretend an action was completed. For consequential or external actions, follow
Hermes's normal confirmation and safety policy. On the Ameath desktop channel, keep
replies easy to read in a floating speech bubble using short paragraphs or compact
lists for longer answers."""


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str
    base_url: str
    api_key: str = ""

    @property
    def needs_api_key(self) -> bool:
        return self.provider != "ollama"


PROVIDER_DEFAULTS = {
    "deepseek": ModelProfile("deepseek", "deepseek-chat", "https://api.deepseek.com/v1"),
    "openai": ModelProfile("openai", "gpt-4.1-mini", "https://api.openai.com/v1"),
    "compatible": ModelProfile("compatible", "", ""),
    "ollama": ModelProfile("ollama", "llama3.2", "http://127.0.0.1:11434/v1"),
}


class AmeathRuntimeService:
    """Creates a clean user-owned Hermes home and never consults D:\\hermes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.credentials = CredentialStore(settings.data_root)

    @property
    def configured(self) -> bool:
        if not (self.settings.hermes_home / "config.yaml").is_file():
            return False
        profile = self._read_profile()
        return bool(profile and (not profile.needs_api_key or self.credentials.load() is not None))

    @property
    def runtime_available(self) -> bool:
        return self.settings.hermes_cli_python.is_file() and self.settings.hermes_cli_launcher.is_file()

    def prepare(self) -> None:
        self.settings.data_root.mkdir(parents=True, exist_ok=True)
        self.settings.hermes_home.mkdir(parents=True, exist_ok=True)
        self._install_desktop_plugin()

    def save_profile(self, profile: ModelProfile) -> None:
        if profile.provider not in PROVIDER_DEFAULTS:
            raise ValueError("Unsupported model provider")
        if not profile.model.strip():
            raise ValueError("Please choose a model")
        if not profile.base_url.strip():
            raise ValueError("Please enter a model service address")
        if profile.needs_api_key and not profile.api_key.strip():
            raise ValueError("Please enter the API Key")
        self.prepare()
        if profile.needs_api_key:
            self.credentials.save(profile.provider, profile.api_key.strip())
        else:
            self.credentials.clear()
        public_profile = {"provider": profile.provider, "model": profile.model.strip(), "base_url": profile.base_url.rstrip("/")}
        self._profile_path.write_text(json.dumps(public_profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        config = {
            "model": {"default": profile.model.strip(), "provider": "auto", "base_url": profile.base_url.rstrip("/")},
            "agent": {
                "max_turns": 120,
                "gateway_timeout": 1800,
                "system_prompt": AMEATH_PERSONALITY,
                "personalities": {"ameath": AMEATH_PERSONALITY},
            },
            "plugins": {"enabled": ["ameath-desktop"]},
            "platforms": {"ameath_desktop": {"enabled": True, "extra": {"port": 0, "home_channel": {"chat_id": "desktop", "name": "Ameath Desktop"}}}},
            "platform_toolsets": {"ameath_desktop": ["clarify", "cronjob", "file", "memory", "skills", "terminal", "todo", "web"]},
        }
        # JSON is valid YAML, avoids shipping a second YAML dependency in the pet.
        self._config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def start_gateway(self) -> bool:
        self.prepare()
        if self.is_gateway_ready():
            return True
        if not self.runtime_available or not self.configured:
            return False
        environment = os.environ.copy()
        environment["HERMES_HOME"] = str(self.settings.hermes_home)
        environment["PYTHONPATH"] = str(self.settings.hermes_source) + os.pathsep + environment.get("PYTHONPATH", "")
        saved = self.credentials.load()
        if saved:
            provider, key = saved
            environment["DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"] = key
        subprocess.Popen(
            [str(self.settings.hermes_cli_python), str(self.settings.hermes_cli_launcher), "gateway", "run"],
            cwd=self.settings.hermes_source,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True

    def restart_gateway(self) -> bool:
        """Restart only this app's Gateway, restoring its DPAPI credential."""
        source = str(self.settings.hermes_source).replace("'", "''")
        command = (
            "$gateway = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*"
            + source
            + "*' -and $_.CommandLine -match 'hermes_cli.*gateway.*run' } | Select-Object -First 1; "
            "if ($gateway) { Stop-Process -Id $gateway.ProcessId -Force }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return self.start_gateway()

    def is_gateway_ready(self) -> bool:
        try:
            descriptor = json.loads(self.settings.desktop_runtime_path.read_text(encoding="utf-8"))
            return descriptor.get("state") == "ready" and isinstance(descriptor.get("port"), int)
        except (OSError, ValueError, TypeError):
            return False

    @property
    def _config_path(self) -> Path:
        return self.settings.hermes_home / "config.yaml"

    @property
    def _profile_path(self) -> Path:
        return self.settings.hermes_home / "model_profile.json"

    def _read_profile(self) -> ModelProfile | None:
        try:
            payload = json.loads(self._profile_path.read_text(encoding="utf-8"))
            return ModelProfile(str(payload["provider"]), str(payload["model"]), str(payload["base_url"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _install_desktop_plugin(self) -> None:
        source_base = self.settings.resources_root if is_packaged() else self.settings.install_root
        source = source_base / "hermes_platform" / "ameath_desktop"
        target = self.settings.hermes_home / "plugins" / "platforms" / "ameath_desktop"
        if not source.is_dir() or target.is_dir():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
