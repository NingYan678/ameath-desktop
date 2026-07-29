"""Safe opt-in integration with an existing local Hermes installation."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Literal

from .config import Settings, is_packaged
from .runtime_descriptor import (
    RuntimeFingerprint,
    RuntimeHealth,
    pid_belongs_to_runtime,
    quick_runtime_health,
    stop_verified_runtime,
)
from .storage import atomic_write_json


LOGGER = logging.getLogger("digital_pet.runtime")
SelectionMode = Literal["shared", "isolated"]


class ProbeStatus(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    INCOMPLETE = "incomplete"
    INVALID_CONFIG = "invalid_config"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class HermesInstallation:
    home: Path
    python: Path
    launcher: Path
    source: Path
    fingerprint: str
    desktop_enabled: bool


@dataclass(frozen=True)
class HermesProbe:
    status: ProbeStatus
    message: str
    installation: HermesInstallation | None = None


@dataclass(frozen=True)
class PreparationResult:
    gateway_running: bool
    desktop_ready: bool
    changed: bool
    unverified_gateway: bool


class BackendSelectionStore:
    """Persists only backend location and a non-secret configuration fingerprint."""

    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "runtime_backend.json"

    def load(self) -> tuple[SelectionMode, Path, str] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            mode, home, fingerprint = payload["mode"], Path(payload["home"]), str(payload["fingerprint"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return (mode, home, fingerprint) if mode in {"shared", "isolated"} else None

    def save(self, mode: SelectionMode, installation: HermesInstallation) -> None:
        atomic_write_json(self.path, {"mode": mode, "home": str(installation.home), "fingerprint": installation.fingerprint})

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _candidate_homes() -> tuple[Path, ...]:
    configured = os.getenv("HERMES_HOME", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(r"D:\hermes"))
    return tuple(dict.fromkeys(candidates))


def discover_existing_hermes(settings: Settings) -> HermesProbe:
    result = HermesProbe(ProbeStatus.MISSING, "未找到本机 Hermes。")
    for home in _candidate_homes():
        result = probe_hermes_home(home, _plugin_source(settings))
        if result.status is ProbeStatus.AVAILABLE:
            return result
    return result


def inspect_hermes_home(home: Path, plugin_source: Path | None = None) -> HermesInstallation | None:
    return probe_hermes_home(home, plugin_source).installation


def probe_hermes_home(home: Path, plugin_source: Path | None = None) -> HermesProbe:
    if not home.is_dir():
        return HermesProbe(ProbeStatus.MISSING, f"未找到 Hermes 路径：{home}")
    config = home / "config.yaml"
    source = home / "hermes-agent"
    python = source / "venv" / "Scripts" / "python.exe"
    launcher = source / "hermes_cli" / "main.py"
    if not config.is_file():
        return HermesProbe(ProbeStatus.INCOMPLETE, "Hermes 缺少 config.yaml。")
    if not python.is_file() or not launcher.is_file():
        return HermesProbe(ProbeStatus.INCOMPLETE, "Hermes 缺少 Python 运行环境或启动器。")
    desktop_enabled = _inspect_config(python, config)
    if desktop_enabled is None:
        return HermesProbe(ProbeStatus.INVALID_CONFIG, "无法解析 Hermes 的 YAML 配置。")
    if plugin_source is not None and not _compatible(python, source, plugin_source):
        return HermesProbe(ProbeStatus.INCOMPATIBLE, "此 Hermes 与爱弥斯桌面插件不兼容。")
    stat = config.stat()
    return HermesProbe(
        ProbeStatus.AVAILABLE,
        "本机 Hermes 可安全接入。",
        HermesInstallation(home, python, launcher, source, f"{stat.st_size}:{stat.st_mtime_ns}", desktop_enabled),
    )


def _inspect_config(python: Path, config: Path) -> bool | None:
    script = """
import json, sys, yaml
from pathlib import Path
try:
    cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding='utf-8')) or {}
    plugins, platforms = cfg.get('plugins') or {}, cfg.get('platforms') or {}
    enabled = 'ameath-desktop' in (plugins.get('enabled') or [])
    desktop = bool((platforms.get('ameath_desktop') or {}).get('enabled'))
    print(json.dumps({'desktop_enabled': bool(enabled and desktop)}))
except Exception:
    sys.exit(2)
"""
    try:
        result = subprocess.run([str(python), "-c", script, str(config)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return bool(json.loads(result.stdout.strip()).get("desktop_enabled")) if not result.returncode else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _compatible(python: Path, source: Path, plugin_source: Path) -> bool:
    manifest = plugin_source / "plugin.yaml"
    try:
        if "name: ameath-desktop" not in manifest.read_text(encoding="utf-8") or not (plugin_source / "adapter.py").is_file():
            return False
    except OSError:
        return False
    script = "import aiohttp, gateway.config, gateway.platforms.base; print('ok')"
    try:
        result = subprocess.run([str(python), "-c", script], cwd=source, capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.returncode == 0 and result.stdout.strip() == "ok"
    except (OSError, subprocess.SubprocessError):
        return False


class ExistingHermesRuntimeService:
    is_shared = True

    def __init__(self, app_settings: Settings, installation: HermesInstallation) -> None:
        self.app_settings = app_settings
        self.installation = installation
        self.settings = replace(app_settings, hermes_home=installation.home, hermes_cli_python=installation.python, hermes_cli_launcher=installation.launcher, hermes_runtime_root=installation.source.parent)
        self._verified_runtime: RuntimeFingerprint | None = None
        self._checked_runtime: RuntimeFingerprint | None = None
        self._checked_health = RuntimeHealth.STOPPED

    @property
    def configured(self) -> bool:
        return True

    @property
    def runtime_available(self) -> bool:
        return self.installation.python.is_file() and self.installation.launcher.is_file()

    @property
    def status_summary(self) -> str:
        return "已验证本机 Hermes" if self.is_gateway_ready() else "等待本机 Hermes Gateway"

    def prepare(self) -> PreparationResult:
        if not _compatible(self.installation.python, self.installation.source, _plugin_source(self.app_settings)):
            raise RuntimeError("本机 Hermes 不兼容爱弥斯桌面插件，未写入任何配置。")
        target = self.installation.home / "plugins" / "platforms" / "ameath_desktop"
        transaction = _ActivationTransaction(self.installation.home / "config.yaml", target)
        changed = False
        try:
            transaction.begin()
            source = _plugin_source(self.app_settings)
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(f".{target.name}.{uuid.uuid4().hex}.new")
            if not _same_tree(source, target):
                try:
                    shutil.copytree(source, staged)
                    if target.exists():
                        shutil.rmtree(target)
                    staged.replace(target)
                finally:
                    if staged.exists():
                        shutil.rmtree(staged, ignore_errors=True)
                transaction.plugin_changed = True
                changed = True
            if not self.installation.desktop_enabled:
                self._enable_desktop_plugin()
                changed = True
        except Exception:
            try:
                transaction.rollback()
            except OSError:
                LOGGER.exception("Shared Hermes plugin rollback failed; transaction backup was retained")
            LOGGER.exception("Rolled back failed local Hermes desktop-plugin activation")
            raise
        else:
            transaction.commit()
        health = self.quick_health()
        return PreparationResult(health is RuntimeHealth.READY, health is RuntimeHealth.READY, changed, False)

    def start_gateway(self) -> bool:
        health = self.quick_health()
        if health in {RuntimeHealth.READY, RuntimeHealth.VERIFYING}:
            return health is RuntimeHealth.READY
        if not self.runtime_available:
            return False
        environment = os.environ.copy()
        environment["HERMES_HOME"] = str(self.installation.home)
        environment["PYTHONPATH"] = str(self.installation.source) + os.pathsep + environment.get("PYTHONPATH", "")
        subprocess.Popen([str(self.installation.python), str(self.installation.launcher), "gateway", "run"], cwd=self.installation.source, env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True

    def restart_gateway(self) -> bool:
        if not stop_verified_runtime(self.settings.desktop_runtime_path, self.installation.source):
            return False
        return self.start_gateway()

    def is_gateway_ready(self) -> bool:
        return self.quick_health() is RuntimeHealth.READY

    def quick_health(self) -> RuntimeHealth:
        health, fingerprint = quick_runtime_health(
            self.settings.desktop_runtime_path,
            self.installation.source,
            None,
        )
        if health is RuntimeHealth.STOPPED:
            return health
        return self._checked_health if fingerprint == self._checked_runtime else RuntimeHealth.VERIFYING

    def verify_identity(self) -> RuntimeHealth:
        health, fingerprint = quick_runtime_health(
            self.settings.desktop_runtime_path,
            self.installation.source,
            None,
        )
        if health is RuntimeHealth.STOPPED or fingerprint is None:
            self._verified_runtime = None
            self._checked_runtime = fingerprint
            self._checked_health = RuntimeHealth.STOPPED
            return RuntimeHealth.STOPPED
        self._checked_runtime = fingerprint
        if pid_belongs_to_runtime(fingerprint.pid, self.installation.source):
            self._verified_runtime = fingerprint
            self._checked_health = RuntimeHealth.READY
            return RuntimeHealth.READY
        self._verified_runtime = None
        self._checked_health = RuntimeHealth.UNTRUSTED
        return RuntimeHealth.UNTRUSTED

    def _enable_desktop_plugin(self) -> None:
        script = """
import os, sys, yaml
sys.path.insert(0, os.environ['HERMES_SOURCE'])
from cli import save_config_value
home = os.environ['HERMES_HOME']
cfg = yaml.safe_load(open(os.path.join(home, 'config.yaml'), encoding='utf-8')) or {}
enabled = list(((cfg.get('plugins') or {}).get('enabled') or []))
if 'ameath-desktop' not in enabled: enabled.append('ameath-desktop')
save_config_value('plugins.enabled', enabled)
save_config_value('platforms.ameath_desktop.enabled', True)
save_config_value('platforms.ameath_desktop.extra', {'port': 0, 'home_channel': {'chat_id': 'desktop', 'name': 'Ameath Desktop'}})
tools = list(((cfg.get('platform_toolsets') or {}).get('ameath_desktop') or []))
for tool in ['clarify', 'cronjob', 'file', 'memory', 'skills', 'terminal', 'todo', 'web']:
    if tool not in tools: tools.append(tool)
save_config_value('platform_toolsets.ameath_desktop', tools)
"""
        environment = os.environ.copy()
        environment["HERMES_HOME"], environment["HERMES_SOURCE"] = str(self.installation.home), str(self.installation.source)
        result = subprocess.run([str(self.installation.python), "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=environment, cwd=self.installation.source, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError("无法在本机 Hermes 中启用爱弥斯桌面插件。")


class _ActivationTransaction:
    def __init__(self, config: Path, plugin_target: Path) -> None:
        self.config, self.plugin_target = config, plugin_target
        self.backup = config.with_name(config.name + f".ameath-txn-{uuid.uuid4().hex}.bak")
        self.plugin_backup = plugin_target.with_name(plugin_target.name + f".ameath-txn-{uuid.uuid4().hex}")
        self.plugin_existed = False
        self.plugin_changed = False

    def begin(self) -> None:
        shutil.copy2(self.config, self.backup)
        self.plugin_existed = self.plugin_target.is_dir()
        if self.plugin_existed:
            shutil.copytree(self.plugin_target, self.plugin_backup)

    def rollback(self) -> None:
        if self.backup.is_file():
            shutil.copy2(self.backup, self.config)
        if self.plugin_changed and self.plugin_target.is_dir():
            shutil.rmtree(self.plugin_target)
        if self.plugin_changed and self.plugin_existed and self.plugin_backup.is_dir():
            shutil.copytree(self.plugin_backup, self.plugin_target)
        self.backup.unlink(missing_ok=True)
        if self.plugin_backup.is_dir():
            shutil.rmtree(self.plugin_backup)

    def commit(self) -> None:
        permanent = self.config.with_name("config.yaml.ameath-backup")
        if not permanent.exists():
            shutil.copy2(self.backup, permanent)
        self.backup.unlink(missing_ok=True)
        if self.plugin_backup.is_dir():
            shutil.rmtree(self.plugin_backup)


def _plugin_source(settings: Settings) -> Path:
    source_root = settings.resources_root if is_packaged() else settings.install_root
    return source_root / "hermes_platform" / "ameath_desktop"


def _same_tree(left: Path, right: Path) -> bool:
    if not right.is_dir():
        return False
    left_files = {path.relative_to(left) for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right) for path in right.rglob("*") if path.is_file()}
    if left_files != right_files:
        return False
    return all(left.joinpath(relative).read_bytes() == right.joinpath(relative).read_bytes() for relative in left_files)
