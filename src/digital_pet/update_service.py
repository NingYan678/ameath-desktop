"""Signed-release metadata validation; download/install remains explicitly user initiated."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    channel: str
    url: str
    sha256: str
    signature: str
    minimum_version: str
    release_notes_url: str


class UpdateService:
    REQUIRED = {"version", "channel", "url", "sha256", "signature", "minimum_version", "release_notes_url"}

    @classmethod
    def parse_manifest(cls, payload: dict[str, object], channel: str) -> UpdateManifest | None:
        if not cls.REQUIRED.issubset(payload) or payload.get("channel") != channel:
            return None
        values = {key: str(payload[key]) for key in cls.REQUIRED}
        if len(values["sha256"]) != 64 or not values["url"].startswith("https://") or not values["signature"]:
            return None
        return UpdateManifest(**values)

    @staticmethod
    def verify_sha256(installer: Path, expected: str) -> bool:
        digest = hashlib.sha256()
        with installer.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().lower() == expected.lower()
