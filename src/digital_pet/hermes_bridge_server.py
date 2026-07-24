"""A narrow, loopback-only persistent Hermes API adapter for the desktop pet."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}")
    return value


def _write_status(state: str, port: int, api_key: str) -> None:
    raw_path = os.getenv("PET_HERMES_BRIDGE_RUNTIME_PATH", "").strip()
    if not raw_path:
        return
    try:
        Path(raw_path).write_text(
            json.dumps(
                {"state": state, "port": port, "pid": os.getpid(), "api_key": api_key},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


async def _serve() -> int:
    agent_root = Path(_required("PET_HERMES_AGENT_ROOT"))
    hermes_home = _required("PET_HERMES_HOME")
    api_key = _required("PET_HERMES_BRIDGE_KEY")
    port = int(_required("PET_HERMES_BRIDGE_PORT"))
    _write_status("starting", port, api_key)
    sys.path.insert(0, str(agent_root))
    os.environ["HERMES_HOME"] = hermes_home

    # Hermes owns its credentials in its existing home. We only load them into
    # this child process; nothing is copied into the pet project.
    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv(hermes_home=hermes_home, project_env=agent_root / ".env")
    os.environ["API_SERVER_KEY"] = api_key

    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "host": "127.0.0.1",
                "port": port,
                "key": api_key,
                "model_name": "ameath-local-butler",
            },
        )
    )
    if not await adapter.connect():
        _write_status("failed", port, api_key)
        return 2
    _write_status("ready", port, api_key)
    try:
        while True:
            await asyncio.sleep(2)
    finally:
        _write_status("stopping", port, api_key)
        await adapter.disconnect()
    return 0


def main() -> int:
    try:
        return asyncio.run(_serve())
    except Exception:
        # Startup details may include provider configuration. The UI exposes a
        # safe generic fallback message instead of writing those details to disk.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
