import json
from pathlib import Path

from digital_pet.animation_catalog import PACKAGED_ASSET_FILES

ROOT = Path(__file__).resolve().parents[1]


def test_installer_cleans_only_replaceable_program_directories():
    script = (ROOT / "packaging" / "Ameath.iss").read_text(encoding="utf-8")

    assert "UsePreviousAppDir=yes" in script
    assert "CloseApplications=force" in script
    assert "if UninstallSilent then" in script
    assert 'Name: "{app}\\app"' in script
    assert 'Name: "{app}\\runtime"' in script
    assert 'Name: "{app}\\licenses"' in script
    install_delete = script.split("[InstallDelete]", 1)[1].split("[Files]", 1)[0]
    assert "{localappdata}\\Ameath" not in install_delete
    assert 'Name: "{app}"' not in install_delete


def test_release_uses_one_version_source():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = (ROOT / "packaging" / "build_release.py").read_text(encoding="utf-8")
    installer = (ROOT / "packaging" / "Ameath.iss").read_text(encoding="utf-8")

    assert version == "1.1.0"
    assert "/DAppVersion={APP_VERSION}" in build
    assert "Ameath-{#AppVersion}-offline-setup" in installer
    assert "#ifndef AppVersion" in installer
    assert "#ifndef AppGuid" in installer
    assert "' + '{#AppGuid}' + '}_is1'" in installer


def test_release_build_uses_temporary_work_and_a_runtime_asset_allowlist():
    build = (ROOT / "packaging" / "build_release.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    development_requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "tempfile.mkdtemp" in build
    assert "prepare_assets(stage)" in build
    assert "platform_root = prepare_platform(stage)" in build
    assert "f\"{platform_root}{separator}hermes_platform\"" in build
    assert "f\"{ROOT / 'hermes_platform'}{separator}hermes_platform\"" not in build
    assert "PACKAGED_ASSET_FILES" in build
    assert "gifs/screen3.gif" in PACKAGED_ASSET_FILES
    assert "gifs/idle1.gif" not in PACKAGED_ASSET_FILES
    assert "httpx" not in build
    assert "httpx" not in requirements
    assert "pytest" not in requirements
    assert "pytest>=8,<9" in development_requirements
    assert "runtime-bootstrap.ps1" not in build
    assert "runtime_url" not in build


def test_release_runtime_is_installed_inside_staging_and_pinned_to_hermes_commit():
    build = (ROOT / "packaging" / "build_release.py").read_text(encoding="utf-8")

    assert "--install-dir" in build
    assert '"--no-bin"' in build
    assert "UV_PYTHON_INSTALL_DIR" in build
    assert '"--link-mode", "copy"' in build
    assert '"aiohttp==3.14.1", "pip"' in build
    assert "runtime_metadata.json" in build
    assert "BUNDLED_HERMES_COMMIT" in build
    assert '"bundled_hermes_commit"' in build
    assert "rev-parse" in build
    assert '"--untracked-files=all"' in build
    assert "is_relative_to(runtime.resolve())" in build
    assert "import hermes_cli" in build
    assert "--version-file" in build
    assert "--icon" in build


def test_companion_content_catalog_is_versioned_and_complete():
    path = ROOT / "assets" / "content" / "companion_zh-CN.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["locale"] == "zh-CN"
    events = payload["proactive_events"]
    ids = [item["event_id"] for item in [*events, *payload["click_interactions"], *payload["drag_interactions"]]]
    assert len(ids) == len(set(ids))
    assert 0.15 <= sum(item.get("expects_reply", False) for item in events) / len(events) <= 0.35
    assert "prepare_content(stage)" in (ROOT / "packaging" / "build_release.py").read_text(encoding="utf-8")
