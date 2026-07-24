from __future__ import annotations

import os
import json
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import Settings


@dataclass
class LocalHermesBridge:
    """Connects to, or starts, the persistent loopback-only Hermes service."""

    settings: Settings
    _process: subprocess.Popen[bytes] | None = field(default=None, init=False)
    _port: int | None = field(default=None, init=False)
    _api_key: str = field(default="", init=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False)
    _failed: threading.Event = field(default_factory=threading.Event, init=False)
    _starting: bool = field(default=False, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def _runtime_path(self) -> Path:
        return self.settings.data_root / ".hermes_bridge_runtime.json"

    @property
    def available(self) -> bool:
        return self._ready.is_set() and (self._process is None or self._process.poll() is None)

    @property
    def base_url(self) -> str:
        if not self.available or self._port is None:
            raise RuntimeError("本机 Hermes 尚未就绪。")
        return f"http://127.0.0.1:{self._port}/v1"

    @property
    def api_key(self) -> str:
        if not self.available:
            raise RuntimeError("本机 Hermes 尚未就绪。")
        return self._api_key

    def start(self) -> None:
        """Reuse the service when it exists, otherwise start it in the background."""
        if self.settings.hermes_backend != "cli":
            return
        if self._load_existing_service():
            return
        with self._lock:
            if self._starting or self.available:
                return
            self._starting = True
            self._failed.clear()
            threading.Thread(target=self._start_worker, name="AmeathHermesBridge", daemon=True).start()

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        # The bridge runs independently from the pet window, so a cached port
        # can become stale after Hermes is restarted. Re-check the loopback
        # service before every chat rather than trusting the in-memory flag.
        if self._load_existing_service():
            return True
        with self._lock:
            self._ready.clear()
        if self.settings.hermes_backend != "cli":
            return False
        self.start()
        wait_seconds = timeout if timeout is not None else self.settings.hermes_bridge_startup_seconds
        return self._ready.wait(wait_seconds) and self.available

    def stop_service(self) -> None:
        """Explicitly stop the independent service (used only by the control script)."""
        runtime = self._read_runtime()
        pid = runtime.get("pid") if runtime else None
        if not isinstance(pid, int) or pid <= 0:
            return
        # The PID comes from our own local runtime record. /T also handles uv's
        # launcher/interpreter arrangement without affecting unrelated Hermes.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        with self._lock:
            self._process = None
            self._ready.clear()
            self._starting = False

    def _start_worker(self) -> None:
        try:
            port = self._find_free_port()
            key = secrets.token_urlsafe(32)
            env = os.environ.copy()
            self.settings.data_root.mkdir(parents=True, exist_ok=True)
            self._runtime_path.unlink(missing_ok=True)
            env.update(
                {
                    "PET_HERMES_BRIDGE_PORT": str(port),
                    "PET_HERMES_BRIDGE_KEY": key,
                    "PET_HERMES_HOME": str(self.settings.hermes_cli_launcher.parent),
                    "PET_HERMES_AGENT_ROOT": str(self.settings.hermes_cli_python.parents[2]),
                    "PET_HERMES_BRIDGE_RUNTIME_PATH": str(self._runtime_path),
                }
            )
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            server = Path(__file__).with_name("hermes_bridge_server.py")
            process = subprocess.Popen(
                [str(self.settings.hermes_cli_python), str(server)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
            with self._lock:
                self._process = process
                self._port = port
                self._api_key = key
            deadline = time.monotonic() + self.settings.hermes_bridge_startup_seconds
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                if self._load_existing_service():
                    return
                time.sleep(0.2)
            self._failed.set()
            if process.poll() is None:
                process.terminate()
        except OSError:
            self._failed.set()
        finally:
            with self._lock:
                self._starting = False

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def _load_existing_service(self) -> bool:
        runtime = self._read_runtime()
        if not runtime:
            return False
        port = runtime.get("port")
        api_key = runtime.get("api_key")
        if runtime.get("state") != "ready" or not isinstance(port, int) or not (1 <= port <= 65535):
            return False
        if not isinstance(api_key, str) or len(api_key) < 16:
            return False
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.7)
        except httpx.HTTPError:
            return False
        if response.status_code != 200:
            return False
        with self._lock:
            self._port = port
            self._api_key = api_key
            self._process = None
            self._ready.set()
        return True

    def _read_runtime(self) -> dict[str, object]:
        try:
            raw = json.loads(self._runtime_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}
