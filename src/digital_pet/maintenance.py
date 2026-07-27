"""Explicit maintenance actions used by the signed installer."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

from .runtime_descriptor import read_runtime_descriptor, stop_verified_runtime


def reset_user_data(data_root: Path, install_root: Path) -> bool:
    """Remove Ameath-owned data without ever terminating a shared Hermes."""
    mode = _backend_mode(data_root / "runtime_backend.json")
    descriptor_path = data_root / "hermes" / "ameath_desktop_runtime.json"
    if mode != "shared" and descriptor_path.exists():
        if read_runtime_descriptor(descriptor_path) is None:
            return False
        if not stop_verified_runtime(descriptor_path, install_root / "runtime" / "hermes-agent"):
            return False
    if not data_root.exists():
        return True

    def make_writable(function, target, _error):  # type: ignore[no-untyped-def]
        Path(target).chmod(stat.S_IWRITE)
        function(target)

    try:
        shutil.rmtree(data_root, onerror=make_writable)
    except OSError:
        return False
    return True


def _backend_mode(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    return str(payload.get("mode", "")) if isinstance(payload, dict) else ""
