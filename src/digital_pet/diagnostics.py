"""Redacted local diagnostics and optional anonymous crash reports."""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import re
import sys
import zipfile
from pathlib import Path

from .version import APP_VERSION


class DiagnosticsService:
    def __init__(self, data_root: Path, *, version: str = APP_VERSION) -> None:
        self.data_root, self.version = data_root, version

    def install_exception_hook(self) -> None:
        previous = sys.excepthook
        def hook(kind, value, trace):  # type: ignore[no-untyped-def]
            logging.getLogger("digital_pet.runtime").exception("Unhandled application exception", exc_info=(kind, value, trace))
            previous(kind, value, trace)
        sys.excepthook = hook

    def export_bundle(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for log in (self.data_root / "logs").glob("*.log"):
                archive.writestr(log.name, self.redact(log.read_text(encoding="utf-8", errors="replace")))
            archive.writestr("environment.json", json.dumps({"version": self.version, "platform": platform.platform()}, ensure_ascii=False, indent=2))
        return destination

    @staticmethod
    def crash_payload(exc: BaseException) -> dict[str, str]:
        return {"exception": type(exc).__name__, "fingerprint": hashlib.sha256(f"{type(exc).__name__}:{exc}".encode()).hexdigest()[:16], "python": platform.python_version(), "system": platform.system()}

    @staticmethod
    def redact(text: str) -> str:
        text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1<redacted>", text)
        text = re.sub(
            r"(?i)([\"']?(?:api[_-]?key|token|authorization|password|secret)[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,}\]]+)",
            r"\1<redacted>",
            text,
        )
        text = re.sub(r"(?i)([?&](?:api[_-]?key|token|password|secret)=)[^&#\s]+", r"\1<redacted>", text)
        return re.sub(r"[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+", "<local-path>", text)
