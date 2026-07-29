"""Windows user-bound storage for setup-wizard API keys."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import POINTER, Structure, byref, c_byte, c_void_p, wintypes
from pathlib import Path


class CredentialError(RuntimeError):
    pass


class _DataBlob(Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(c_byte))]


_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[c_byte]]:
    buffer = (c_byte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), buffer), buffer


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialError("This installer stores model credentials only on Windows.")
    source, source_buffer = _blob(data)
    target = _DataBlob()
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    success = crypt.CryptProtectData(byref(source), "Ameath model credential", None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, byref(target))
    if not success:
        raise CredentialError("Windows could not protect the model credential.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(target.pbData, c_void_p))


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialError("This installer stores model credentials only on Windows.")
    source, source_buffer = _blob(data)
    target = _DataBlob()
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    success = crypt.CryptUnprotectData(byref(source), None, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, byref(target))
    if not success:
        raise CredentialError("The saved model credential belongs to another Windows user.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(target.pbData, c_void_p))


class CredentialStore:
    """Stores one provider key encrypted by Windows DPAPI for this user only."""

    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "secrets" / "model_credential.json"

    def save(self, provider: str, api_key: str) -> None:
        encrypted = _protect(api_key.encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"provider": provider, "blob": base64.b64encode(encrypted).decode("ascii")}),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def load(self) -> tuple[str, str] | None:
        credential, _reason = self.load_with_status()
        return credential

    def load_with_status(self) -> tuple[tuple[str, str] | None, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            provider = str(payload["provider"])
            encrypted = base64.b64decode(str(payload["blob"]), validate=True)
            return (provider, _unprotect(encrypted).decode("utf-8")), "available"
        except FileNotFoundError:
            return None, "missing"
        except CredentialError:
            return None, "dpapi-unavailable"
        except (OSError, ValueError, KeyError, UnicodeDecodeError):
            return None, "invalid"

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
