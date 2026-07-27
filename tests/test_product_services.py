import hashlib

from digital_pet.diagnostics import DiagnosticsService
from digital_pet.update_service import UpdateService


def test_diagnostics_redacts_credentials_and_user_paths(tmp_path):
    service = DiagnosticsService(tmp_path)
    redacted = service.redact(r"token=secret-value api_key: abc E:\work\Ameath\private")

    assert "secret-value" not in redacted
    assert "abc" not in redacted
    assert "Ameath" not in redacted


def test_update_manifest_requires_secure_complete_metadata():
    payload = {
        "version": "1.0.1",
        "channel": "stable",
        "url": "https://example.test/Ameath.exe",
        "sha256": "a" * 64,
        "signature": "base64-signature",
        "minimum_version": "1.0.0",
        "release_notes_url": "https://example.test/releases/1.0.1",
    }

    manifest = UpdateService.parse_manifest(payload, "stable")

    assert manifest.version == "1.0.1"
    assert UpdateService.parse_manifest({**payload, "url": "http://example.test/Ameath.exe"}, "stable") is None


def test_update_hash_verification(tmp_path):
    package = tmp_path / "Ameath.exe"
    package.write_bytes(b"signed package")
    assert UpdateService.verify_sha256(package, hashlib.sha256(b"signed package").hexdigest())
    assert not UpdateService.verify_sha256(package, "0" * 64)
