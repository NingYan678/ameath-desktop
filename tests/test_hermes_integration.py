"""Opt-in smoke test for a disposable, real Hermes installation.

Set HERMES_INTEGRATION_HOME to a temporary copy of Hermes; never point it at a
personal installation because this test enables the Ameath desktop plugin.
"""

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

from digital_pet.config import Settings
from digital_pet.existing_hermes import ExistingHermesRuntimeService, probe_hermes_home

INTEGRATION_HOME = os.getenv("HERMES_INTEGRATION_HOME", "").strip()
pytestmark = pytest.mark.skipif(not INTEGRATION_HOME, reason="requires disposable HERMES_INTEGRATION_HOME")


def test_real_hermes_writes_a_pid_runtime_and_serves_health_endpoint():
    root = Path(__file__).parents[1]
    home = Path(INTEGRATION_HOME)
    settings = Settings(root / "assets", root / "data", Path("missing"), Path("missing"), install_root=root)
    probe = probe_hermes_home(home, root / "hermes_platform" / "ameath_desktop")
    assert probe.installation is not None, probe.message
    runtime = ExistingHermesRuntimeService(settings, probe.installation)
    result = runtime.prepare()
    if result.unverified_gateway:
        pytest.skip("the disposable Hermes Gateway is already running")
    assert runtime.start_gateway()
    descriptor_path = runtime.settings.desktop_runtime_path
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not runtime.is_gateway_ready():
            time.sleep(0.25)
        assert runtime.is_gateway_ready()
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        assert isinstance(descriptor.get("pid"), int)
        with urlopen(f"http://127.0.0.1:{descriptor['port']}/health", timeout=3) as response:
            assert json.loads(response.read())["status"] == "ok"
    finally:
        descriptor = runtime._runtime_descriptor()
        if descriptor is not None:
            subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {descriptor['pid']} -Force"], check=False)
