"""Non-sensitive Hermes configuration bridge for the desktop settings page."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_HERMES_PYTHON = Path(r"D:\hermes\hermes-agent\venv\Scripts\python.exe")
DEFAULT_HERMES_SOURCE = Path(r"D:\hermes\hermes-agent")
MANAGED_TOOLSETS = (
    "browser", "clarify", "code_execution", "computer_use", "cronjob", "delegation", "file",
    "image_gen", "kanban", "memory", "session_search", "skills", "terminal", "todo", "tts", "vision", "web",
)


@dataclass(frozen=True)
class HermesSettingsSnapshot:
    model: str
    provider: str
    active_personality: str
    personalities: tuple[str, ...]
    enabled_tools: tuple[str, ...]
    gateway_running: bool


class HermesSettingsService:
    """Reads and writes only global non-secret Hermes options."""

    def __init__(
        self,
        hermes_home: Path,
        *,
        python: Path = DEFAULT_HERMES_PYTHON,
        source: Path = DEFAULT_HERMES_SOURCE,
        restart_handler: Callable[[], bool] | None = None,
    ) -> None:
        self.hermes_home = hermes_home
        self.python = python
        self.source = source
        self._restart_handler = restart_handler

    def read(self) -> HermesSettingsSnapshot:
        script = """
import json, os, yaml
from pathlib import Path
home = Path(os.environ['HERMES_HOME'])
try:
    cfg = yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8')) or {}
except Exception:
    cfg = {}
model = cfg.get('model') or {}
agent = cfg.get('agent') or {}
personalities = agent.get('personalities') or {}
platform_tools = cfg.get('platform_toolsets') or {}
tools = sorted({str(tool) for values in platform_tools.values() if isinstance(values, list) for tool in values if not str(tool).startswith('hermes-')})
print(json.dumps({'model': str(model.get('default') or ''), 'provider': str(model.get('provider') or ''), 'active_personality': str((cfg.get('display') or {}).get('personality') or 'none'), 'personalities': sorted(str(name) for name in personalities), 'enabled_tools': tools}, ensure_ascii=False))
"""
        payload = self._run_json(script)
        return HermesSettingsSnapshot(
            model=str(payload.get("model", "")),
            provider=str(payload.get("provider", "")),
            active_personality=str(payload.get("active_personality", "none")),
            personalities=tuple(str(item) for item in payload.get("personalities", []) if str(item)),
            enabled_tools=tuple(str(item) for item in payload.get("enabled_tools", []) if str(item)),
            gateway_running=self._gateway_running(),
        )

    def apply_and_restart(self, *, model: str, provider: str, personality: str, tools: Iterable[str]) -> None:
        selected_tools = sorted({tool for tool in tools if tool and not tool.startswith("hermes-")})
        payload = json.dumps(
            {"model": model.strip(), "provider": provider.strip(), "personality": personality.strip(), "tools": selected_tools},
            ensure_ascii=False,
        )
        script = """
import json, os, sys
sys.path.insert(0, os.environ['HERMES_SOURCE'])
from cli import save_config_value
from gateway.run import _load_gateway_runtime_config
requested = json.loads(sys.argv[1])
cfg = _load_gateway_runtime_config()
personalities = (cfg.get('agent') or {}).get('personalities') or {}
name = requested['personality']
if name and name not in {'none', 'default', 'neutral'} and name not in personalities:
    raise ValueError(f'Unknown Hermes personality: {name}')
if not requested['model']:
    raise ValueError('Model cannot be empty')
save_config_value('model.default', requested['model'])
save_config_value('model.provider', requested['provider'] or 'auto')
save_config_value('display.personality', name or 'none')
value = None if name in {'', 'none', 'default', 'neutral'} else personalities[name]
if isinstance(value, dict):
    prompt = '\\n'.join(str(value.get(key, '')).strip() for key in ('system_prompt', 'tone', 'style') if str(value.get(key, '')).strip())
else:
    prompt = '' if value is None else str(value)
save_config_value('agent.system_prompt', prompt)
platform_tools = cfg.get('platform_toolsets') or {}
for platform, values in platform_tools.items():
    existing = [str(item) for item in values] if isinstance(values, list) else []
    preserved = [item for item in existing if item.startswith('hermes-')]
    save_config_value(f'platform_toolsets.{platform}', preserved + requested['tools'])
print(json.dumps({'saved': True}))
"""
        self._run_json(script, payload)
        self.restart_gateway()

    def restart_gateway(self) -> None:
        if self._restart_handler is not None:
            self._restart_handler()
            return
        source = str(self.source).replace("'", "''")
        python = str(self.python).replace("'", "''")
        launcher = str(self.source / "hermes_cli" / "main.py").replace("'", "''")
        home = str(self.hermes_home).replace("'", "''")
        command = (
            "$gateway = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + source + "*' -and $_.CommandLine -match 'hermes_cli.*gateway.*run' } | Select-Object -First 1; "
            "if ($gateway) { Stop-Process -Id $gateway.ProcessId -Force }; "
            "Start-Sleep -Seconds 2; "
            "$env:HERMES_HOME = '" + home + "'; "
            "$env:PYTHONPATH = '" + source + "'; "
            "Start-Process -FilePath '" + python + "' -ArgumentList '" + launcher + "','gateway','run' -WorkingDirectory '" + source + "' -WindowStyle Hidden"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _run_json(self, script: str, *arguments: str) -> dict:
        if not self.python.is_file():
            raise RuntimeError("未找到 Hermes 配置运行环境。")
        environment = os.environ.copy()
        environment["HERMES_HOME"] = str(self.hermes_home)
        environment["HERMES_SOURCE"] = str(self.source)
        result = subprocess.run(
            [str(self.python), "-c", script, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Hermes 配置更新失败。")
        try:
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError("Hermes 返回了无法读取的配置结果。") from exc

    def _gateway_running(self) -> bool:
        try:
            runtime = json.loads((self.hermes_home / "ameath_desktop_runtime.json").read_text(encoding="utf-8"))
            return runtime.get("state") == "ready" and isinstance(runtime.get("port"), int)
        except (OSError, ValueError, TypeError):
            return False
