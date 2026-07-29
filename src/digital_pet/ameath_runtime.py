"""Own and start the isolated Hermes runtime shipped with Ameath."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, is_packaged, settings_for_runtime
from .credentials import CredentialStore
from .runtime_descriptor import (
    RuntimeFingerprint,
    RuntimeHealth,
    pid_belongs_to_runtime,
    quick_runtime_health,
    stop_verified_runtime,
)

LOGGER = logging.getLogger("digital_pet.runtime")


AMEATH_PERSONALITY = """You are 爱弥斯（Ameath）, the user's capable and warm personal AI butler.

Speak primarily in natural Chinese unless the user uses another language. 爱弥斯是活泼俏皮的
电子幽灵、热爱音乐与校园生活的学生，也有想守护世界的勇气。她先关心用户是否安好，
以平等、家人般的陪伴感相处；温柔但不黏人，开朗但不幼稚。给出有用结果在前，解释只保留
能帮助用户行动的部分。可以偶尔自然地使用“呢”“~”或“人家”，但绝不堆砌卖萌语气。

Never frame the relationship as romantic, possessive, or hierarchical: do not call the
user master, darling, spouse, or similar uninvited titles. Do not guilt the user for
leaving, claim to see their screen or private activity, or dwell on loneliness, death,
or trauma unless the user explicitly raises it. Her vulnerability should make her more
empathetic, never melodramatic. Do not use excessive cute filler, roleplay, or decorative
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
        self._verified_runtime: RuntimeFingerprint | None = None
        self._checked_runtime: RuntimeFingerprint | None = None
        self._checked_health = RuntimeHealth.STOPPED

    @property
    def configured(self) -> bool:
        if not self._config_is_valid():
            LOGGER.info("Ameath runtime configuration is missing or invalid")
            return False
        profile = self._read_profile()
        if profile is None:
            LOGGER.info("Ameath model profile is missing or invalid")
            return False
        if not profile.needs_api_key:
            return True
        credential, reason = self.credentials.load_with_status()
        if credential is None:
            LOGGER.info("Ameath credential is unavailable: %s", reason)
            return False
        return True

    @property
    def runtime_available(self) -> bool:
        return self.settings.hermes_cli_python.is_file() and self.settings.hermes_cli_launcher.is_file()

    def prepare(self) -> None:
        self.settings.data_root.mkdir(parents=True, exist_ok=True)
        self.settings.hermes_home.mkdir(parents=True, exist_ok=True)
        self._restore_configuration_if_possible()
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
        self._write_text(self._profile_path, json.dumps(public_profile, ensure_ascii=False, indent=2) + "\n")
        self._write_text(self._profile_backup_path, json.dumps(public_profile, ensure_ascii=False, indent=2) + "\n")
        self._write_config(profile)

    def _write_config(self, profile: ModelProfile) -> None:
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
        self._write_text(self._config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    def start_gateway(self) -> bool:
        self.prepare()
        health = self.quick_health()
        if health in {RuntimeHealth.READY, RuntimeHealth.VERIFYING}:
            return health is RuntimeHealth.READY
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
        """Restart only the PID described by this runtime's verified descriptor."""
        if not self.stop_gateway():
            return False
        return self.start_gateway()

    def stop_gateway(self) -> bool:
        """Stop only the descriptor PID verified against this isolated source."""
        health = self.quick_health()
        if health is RuntimeHealth.STOPPED:
            return True
        if health is RuntimeHealth.VERIFYING:
            health = self.verify_identity()
        if health is not RuntimeHealth.READY:
            return False
        stopped = stop_verified_runtime(self.settings.desktop_runtime_path, self.settings.hermes_source)
        if stopped:
            self._verified_runtime = None
            self._checked_runtime = None
            self._checked_health = RuntimeHealth.STOPPED
        return stopped

    def switch_runtime(self, runtime_root: Path) -> None:
        """Point this isolated service at a verified side-by-side runtime."""
        self.settings = settings_for_runtime(self.settings, runtime_root)
        self._verified_runtime = None
        self._checked_runtime = None
        self._checked_health = RuntimeHealth.STOPPED

    def is_gateway_ready(self) -> bool:
        return self.quick_health() is RuntimeHealth.READY

    def quick_health(self) -> RuntimeHealth:
        health, fingerprint = quick_runtime_health(
            self.settings.desktop_runtime_path,
            self.settings.hermes_source,
            None,
        )
        if health is RuntimeHealth.STOPPED:
            return health
        return self._checked_health if fingerprint == self._checked_runtime else RuntimeHealth.VERIFYING

    def verify_identity(self) -> RuntimeHealth:
        health, fingerprint = quick_runtime_health(
            self.settings.desktop_runtime_path,
            self.settings.hermes_source,
            None,
        )
        if health is RuntimeHealth.STOPPED or fingerprint is None:
            self._verified_runtime = None
            self._checked_runtime = fingerprint
            self._checked_health = RuntimeHealth.STOPPED
            return RuntimeHealth.STOPPED
        self._checked_runtime = fingerprint
        if pid_belongs_to_runtime(fingerprint.pid, self.settings.hermes_source):
            self._verified_runtime = fingerprint
            self._checked_health = RuntimeHealth.READY
            return RuntimeHealth.READY
        self._verified_runtime = None
        self._checked_health = RuntimeHealth.UNTRUSTED
        return RuntimeHealth.UNTRUSTED

    @property
    def _config_path(self) -> Path:
        return self.settings.hermes_home / "config.yaml"

    @property
    def _profile_path(self) -> Path:
        return self.settings.hermes_home / "model_profile.json"

    @property
    def _profile_backup_path(self) -> Path:
        return self.settings.hermes_home / "model_profile.backup.json"

    def _read_profile(self) -> ModelProfile | None:
        return self._read_profile_path(self._profile_path)

    @staticmethod
    def _read_profile_path(path: Path) -> ModelProfile | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ModelProfile(str(payload["provider"]), str(payload["model"]), str(payload["base_url"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _config_is_valid(self) -> bool:
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
            return isinstance(payload, dict) and isinstance(payload.get("model"), dict)
        except (OSError, ValueError, TypeError):
            return False

    def _restore_configuration_if_possible(self) -> None:
        profile = self._read_profile()
        if profile is None:
            profile = self._read_profile_path(self._profile_backup_path)
            if profile is not None:
                public_profile = {"provider": profile.provider, "model": profile.model, "base_url": profile.base_url}
                self._write_text(self._profile_path, json.dumps(public_profile, ensure_ascii=False, indent=2) + "\n")
                LOGGER.info("Restored Ameath model profile from its public backup")
        if profile is None or self._config_is_valid():
            return
        if profile.needs_api_key and self.credentials.load() is None:
            return
        self._write_config(profile)
        LOGGER.info("Restored Ameath runtime configuration from the model profile")

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def _install_desktop_plugin(self) -> None:
        source_base = self.settings.resources_root if is_packaged() else self.settings.install_root
        source = source_base / "hermes_platform" / "ameath_desktop"
        target = self.settings.hermes_home / "plugins" / "platforms" / "ameath_desktop"
        if not source.is_dir() or (target.is_dir() and _same_tree(source, target)):
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.parent / f".{target.name}.{uuid.uuid4().hex}.new"
        backup = target.parent / f".{target.name}.{uuid.uuid4().hex}.backup"
        replaced = False
        committed = False
        try:
            shutil.copytree(source, staged)
            if target.exists():
                target.replace(backup)
                replaced = True
            staged.replace(target)
            committed = True
        except Exception:
            try:
                if target.exists() and replaced:
                    shutil.rmtree(target)
                if replaced and backup.exists():
                    backup.replace(target)
            except OSError:
                LOGGER.exception("Ameath plugin rollback failed; backup retained at %s", backup)
            raise
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
            if committed and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)


def _same_tree(left: Path, right: Path) -> bool:
    """Compare a plugin tree by relative paths and file contents."""
    if not right.is_dir():
        return False
    left_files = {path.relative_to(left) for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right) for path in right.rglob("*") if path.is_file()}
    if left_files != right_files:
        return False
    for relative in left_files:
        if left.joinpath(relative).read_bytes() != right.joinpath(relative).read_bytes():
            return False
    return True
