"""Desktop-only Hermes configuration bridge for an isolated Ameath runtime."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

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
    """Reads and atomically updates only the isolated Ameath desktop channel."""

    def __init__(self, hermes_home: Path, *, python: Path, source: Path, restart_handler: Callable[[], bool]) -> None:
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
except (OSError, ValueError, yaml.YAMLError):
    cfg = {}
model = cfg.get('model') or {}
agent = cfg.get('agent') or {}
personalities = agent.get('personalities') or {}
platform_tools = cfg.get('platform_toolsets') or {}
tools = platform_tools.get('ameath_desktop') or []
print(json.dumps({'model': str(model.get('default') or ''), 'provider': str(model.get('provider') or ''), 'active_personality': str((cfg.get('display') or {}).get('personality') or 'none'), 'personalities': sorted(str(name) for name in personalities), 'enabled_tools': sorted(str(tool) for tool in tools if not str(tool).startswith('hermes-'))}, ensure_ascii=False))
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
import json, os, tempfile, yaml
from pathlib import Path
requested = json.loads(__import__('sys').argv[1])
home = Path(os.environ['HERMES_HOME'])
path = home / 'config.yaml'
cfg = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
if not isinstance(cfg, dict):
    raise ValueError('Hermes config must be an object')
personalities = (cfg.get('agent') or {}).get('personalities') or {}
name = requested['personality']
if name and name not in {'none', 'default', 'neutral'} and name not in personalities:
    raise ValueError(f'Unknown Hermes personality: {name}')
if not requested['model']:
    raise ValueError('Model cannot be empty')
model = dict(cfg.get('model') or {})
model['default'] = requested['model']
model['provider'] = requested['provider'] or 'auto'
cfg['model'] = model
display = dict(cfg.get('display') or {})
display['personality'] = name or 'none'
cfg['display'] = display
value = None if name in {'', 'none', 'default', 'neutral'} else personalities[name]
if isinstance(value, dict):
    prompt = chr(10).join(str(value.get(key, '')).strip() for key in ('system_prompt', 'tone', 'style') if str(value.get(key, '')).strip())
else:
    prompt = '' if value is None else str(value)
agent = dict(cfg.get('agent') or {})
agent['system_prompt'] = prompt
cfg['agent'] = agent
toolsets = dict(cfg.get('platform_toolsets') or {})
existing = [str(item) for item in toolsets.get('ameath_desktop') or []]
toolsets['ameath_desktop'] = [item for item in existing if item.startswith('hermes-')] + requested['tools']
cfg['platform_toolsets'] = toolsets
temporary = path.with_suffix(path.suffix + '.ameath.tmp')
temporary.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
os.replace(temporary, path)
print(json.dumps({'saved': True}))
"""
        self._run_json(script, payload)
        if not self._restart_handler():
            raise RuntimeError("Hermes Gateway 未能安全重启；配置已保存，请在 Hermes 中手动启动后重试连接。")

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
