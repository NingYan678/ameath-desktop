"""Redacted local diagnostics generated entirely on the user's machine."""

from __future__ import annotations

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
                sanitized = self.redact(log.read_text(encoding="utf-8", errors="replace"))
                if self.redact(sanitized) != sanitized:
                    raise ValueError(f"Diagnostic redaction was not stable for {log.name}")
                archive.writestr(log.name, sanitized)
            archive.writestr("environment.json", json.dumps({"version": self.version, "platform": platform.platform()}, ensure_ascii=False, indent=2))
        return destination

    @staticmethod
    def redact(text: str) -> str:
        text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1<redacted>", text)
        sensitive_key = r"(?:access[_-]?token|refresh[_-]?token|client[_-]?secret|api[_-]?(?:key|secret)|secret(?:[_-]?key)?|token|authorization|password)"
        text = re.sub(
            rf"(?i)([\"']?{sensitive_key}[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,}}\]]+)",
            r"\1<redacted>",
            text,
        )
        text = re.sub(rf"(?i)([?&]{sensitive_key}=)[^&#\s]+", r"\1<redacted>", text)
        return re.sub(r"(?i)(?<![A-Za-z0-9])(?:[A-Za-z]:\\|\\\\)[^\"\r\n,;}]+", "<local-path>", text)
