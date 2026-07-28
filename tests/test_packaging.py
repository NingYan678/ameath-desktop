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

    assert version == "1.0.0"
    assert "/DAppVersion={APP_VERSION}" in build
    assert "Ameath-{#AppVersion}-{#BuildMode}-setup" in installer
    assert "#ifndef AppVersion" in installer
    assert "#ifndef AppGuid" in installer
    assert "' + '{#AppGuid}' + '}_is1'" in installer


def test_release_build_uses_temporary_work_and_a_runtime_asset_allowlist():
    build = (ROOT / "packaging" / "build_release.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    development_requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "tempfile.mkdtemp" in build
    assert "prepare_assets(stage)" in build
    assert "PACKAGED_ASSET_FILES" in build
    assert "gifs/screen3.gif" in PACKAGED_ASSET_FILES
    assert "gifs/idle1.gif" not in PACKAGED_ASSET_FILES
    assert "httpx" not in build
    assert "httpx" not in requirements
    assert "pytest" not in requirements
    assert "pytest>=8,<9" in development_requirements


def test_release_runtime_is_installed_inside_staging_and_pinned_to_hermes_commit():
    build = (ROOT / "packaging" / "build_release.py").read_text(encoding="utf-8")

    assert "--install-dir" in build
    assert "UV_PYTHON_INSTALL_DIR" in build
    assert '"--link-mode", "copy"' in build
    assert "runtime_metadata.json" in build
    assert "rev-parse" in build
    assert "is_relative_to(runtime.resolve())" in build
    assert "import hermes_cli" in build
