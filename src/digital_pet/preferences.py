"""Persistent, non-sensitive preferences for the local desktop surface."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DesktopPreferences:
    pet_size: int = 200
    compact_width: int = 360
    expanded_width: int = 520
    expanded_height: int = 408
    panel_opacity: int = 58
    font_scale: int = 100
    animation_speed: int = 100
    auto_collapse_seconds: int = 30
    always_on_top: bool = True
    launch_at_login: bool = False


class UISettingsStore:
    """Stores display-only preferences separately from Hermes configuration."""

    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "ui_settings.json"

    def load(self) -> DesktopPreferences:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return DesktopPreferences()
        if not isinstance(payload, dict):
            return DesktopPreferences()
        defaults = DesktopPreferences()
        return DesktopPreferences(
            pet_size=self._bounded_int(payload.get("pet_size"), defaults.pet_size, 120, 360),
            compact_width=self._bounded_int(payload.get("compact_width"), defaults.compact_width, 300, 560),
            expanded_width=self._bounded_int(payload.get("expanded_width"), defaults.expanded_width, 380, 760),
            expanded_height=self._bounded_int(payload.get("expanded_height"), defaults.expanded_height, 280, 760),
            panel_opacity=self._bounded_int(payload.get("panel_opacity"), defaults.panel_opacity, 20, 100),
            font_scale=self._bounded_int(payload.get("font_scale"), defaults.font_scale, 80, 150),
            animation_speed=self._bounded_int(payload.get("animation_speed"), defaults.animation_speed, 50, 200),
            auto_collapse_seconds=self._bounded_int(payload.get("auto_collapse_seconds"), defaults.auto_collapse_seconds, 5, 180),
            always_on_top=bool(payload.get("always_on_top", defaults.always_on_top)),
            launch_at_login=bool(payload.get("launch_at_login", defaults.launch_at_login)),
        )

    def save(self, preferences: DesktopPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix="ui_settings_", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(asdict(preferences), output, ensure_ascii=False, indent=2)
                output.write("\n")
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @staticmethod
    def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(value)))
        except (TypeError, ValueError):
            return default


class StartupManager:
    """User-level Windows startup entry for the local desktop surface only."""

    VALUE_NAME = "AmeathDesktopPet"
    KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self, launch_command: str | Path) -> None:
        self._command = str(launch_command)

    def is_enabled(self) -> bool:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, self.VALUE_NAME)
                return value == self._command
        except OSError:
            return False

    def set_enabled(self, enabled: bool) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.KEY_PATH) as key:
            if enabled:
                winreg.SetValueEx(key, self.VALUE_NAME, 0, winreg.REG_SZ, self._command)
            else:
                try:
                    winreg.DeleteValue(key, self.VALUE_NAME)
                except FileNotFoundError:
                    pass
