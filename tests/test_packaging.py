from pathlib import Path


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
