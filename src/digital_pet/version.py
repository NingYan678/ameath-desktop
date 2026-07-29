"""Single application version source shared with release packaging."""

from __future__ import annotations

import sys
from pathlib import Path


def _read_version() -> str:
    roots = [Path(sys._MEIPASS)] if hasattr(sys, "_MEIPASS") else []
    roots.append(Path(__file__).resolve().parents[2])
    for root in roots:
        try:
            value = (root / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return "0.0.0"


APP_VERSION = _read_version()
