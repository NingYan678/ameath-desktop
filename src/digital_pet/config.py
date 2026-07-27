"""Runtime paths for development and the self-contained Windows install."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def application_root() -> Path:
    """The immutable app directory, never the user's Hermes data directory."""
    return Path(sys.executable).resolve().parent.parent if is_packaged() else PROJECT_ROOT


def resource_root() -> Path:
    """PyInstaller data directory in releases, project root while developing."""
    return Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) if is_packaged() else PROJECT_ROOT


def default_data_root() -> Path:
    override = os.getenv("AMEATH_DATA_HOME", "").strip()
    if override:
        return Path(override)
    return Path(os.getenv("LOCALAPPDATA", str(PROJECT_ROOT / "data"))) / "Ameath"


def _development_hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", r"D:\hermes"))


DEFAULT_HERMES_HOME = default_data_root() / "hermes" if is_packaged() else _development_hermes_home()


@dataclass(frozen=True)
class Settings:
    asset_root: Path
    data_root: Path
    hermes_base_url: str
    hermes_api_key: str
    hermes_model: str
    hermes_timeout_seconds: float
    hermes_cli_python: Path
    hermes_cli_launcher: Path
    hermes_bridge_startup_seconds: float = 25.0
    hermes_home: Path = DEFAULT_HERMES_HOME
    install_root: Path = PROJECT_ROOT
    hermes_runtime_root: Path = Path()

    @property
    def desktop_runtime_path(self) -> Path:
        """Gateway-owned local descriptor; it is never shared outside this PC."""
        return self.hermes_home / "ameath_desktop_runtime.json"

    @property
    def hermes_source(self) -> Path:
        """Hermes source shipped beside the app, or the development source tree."""
        if self.hermes_runtime_root:
            candidate = self.hermes_runtime_root / "hermes-agent"
            if candidate.is_dir():
                return candidate
        return self.hermes_cli_launcher.parent.parent

    @property
    def launch_command(self) -> str:
        if is_packaged():
            return f'"{Path(sys.executable).resolve()}"'
        return f'wscript.exe //B "{PROJECT_ROOT / "run.vbs"}"'

    @property
    def resources_root(self) -> Path:
        return resource_root()

    @property
    def hermes_backend(self) -> str:
        if self.hermes_base_url and self.hermes_model:
            return "http"
        if self.hermes_cli_python.is_file() and self.hermes_cli_launcher.is_file():
            return "cli"
        return "none"

    @property
    def hermes_enabled(self) -> bool:
        return self.hermes_backend != "none"


def load_settings() -> Settings:
    # .env remains a development convenience. Installed copies use the setup
    # wizard and user data directory instead, so no secrets ship in the app.
    if not is_packaged():
        load_dotenv(PROJECT_ROOT / ".env")
    install_root = application_root()
    data_root = default_data_root() if is_packaged() else Path(os.getenv("AMEATH_DATA_HOME", str(PROJECT_ROOT / "data")))
    runtime_root = Path(os.getenv("AMEATH_RUNTIME_ROOT", str(install_root / "runtime")))
    if is_packaged():
        default_home = data_root / "hermes"
        default_python = runtime_root / "python" / "python.exe"
        default_launcher = runtime_root / "hermes-agent" / "hermes_cli" / "main.py"
    else:
        default_home = _development_hermes_home()
        default_python = default_home / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
        default_launcher = default_home / "hermes-agent" / "hermes_cli" / "main.py"
    try:
        timeout = max(1.0, float(os.getenv("HERMES_TIMEOUT_SECONDS", "60")))
    except ValueError:
        timeout = 60.0
    try:
        bridge_startup_seconds = max(3.0, float(os.getenv("HERMES_BRIDGE_STARTUP_SECONDS", "25")))
    except ValueError:
        bridge_startup_seconds = 25.0
    return Settings(
        asset_root=Path(os.getenv("AMEATH_ASSET_ROOT", str(resource_root() / "assets" / "recovered"))),
        data_root=data_root,
        hermes_base_url=os.getenv("HERMES_BASE_URL", "").strip().rstrip("/"),
        hermes_api_key=os.getenv("HERMES_API_KEY", "").strip(),
        hermes_model=os.getenv("HERMES_MODEL", "").strip(),
        hermes_timeout_seconds=timeout,
        # A packaged app must never inherit the developer's HERMES_* paths.
        # Those variables often point at an existing personal Gateway and would
        # silently merge the two assistants. Advanced package testing may use
        # the explicitly namespaced AMEATH_* overrides instead.
        hermes_cli_python=Path(os.getenv("AMEATH_HERMES_PYTHON", str(default_python))) if is_packaged() else Path(os.getenv("HERMES_CLI_PYTHON", str(default_python))),
        hermes_cli_launcher=Path(os.getenv("AMEATH_HERMES_LAUNCHER", str(default_launcher))) if is_packaged() else Path(os.getenv("HERMES_CLI_LAUNCHER", str(default_launcher))),
        hermes_bridge_startup_seconds=bridge_startup_seconds,
        hermes_home=Path(os.getenv("AMEATH_HERMES_HOME", str(default_home))) if is_packaged() else Path(os.getenv("HERMES_HOME", str(default_home))),
        install_root=install_root,
        hermes_runtime_root=runtime_root,
    )
