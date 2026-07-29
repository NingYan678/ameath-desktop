"""Build the reproducible offline Windows installer for Ameath."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from digital_pet.animation_catalog import PACKAGED_ASSET_FILES

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_HERMES_COMMIT = "41a07f5b8451f88a8b8b5adfc0cfdc2ada0a1f90"
APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", APP_VERSION) is None:
    raise RuntimeError("VERSION must contain a valid SemVer value")
SKIP_SOURCE_NAMES = {".git", ".github", ".plans", "tests", "tests-js", "docs", "website", "node_modules", "venv", ".venv", ".cache", "build", "dist", "__pycache__"}
ASSET_FILES = PACKAGED_ASSET_FILES
CONTENT_FILES = frozenset({"content/companion_zh-CN.json"})


def run(*command: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def remove_tree(path: Path) -> None:
    """Remove prior build output even when Windows copied read-only files."""
    if not path.exists():
        return

    def retry(function, target, _exception):  # type: ignore[no-untyped-def]
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onerror=retry)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksum(path: Path) -> Path:
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{sha256(path)}  {path.name}\n", encoding="utf-8")
    return checksum_path


def ignore_source(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_SOURCE_NAMES or name.endswith(".pyc")}


def prepare_assets(stage: Path) -> Path:
    source_root = ROOT / "assets" / "recovered"
    target_root = stage / "assets" / "recovered"
    available = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    if available != ASSET_FILES:
        missing = sorted(ASSET_FILES - available)
        extra = sorted(available - ASSET_FILES)
        raise RuntimeError(f"Packaged asset directory does not match manifest: missing={missing}, extra={extra}")
    for relative_name in ASSET_FILES:
        source = source_root / relative_name
        if not source.is_file():
            raise RuntimeError(f"Required packaged asset is missing: {source}")
        target = target_root / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    prepare_content(stage)
    return stage / "assets"


def prepare_content(stage: Path) -> Path:
    source_root = ROOT / "assets"
    target_root = stage / "assets"
    available = {
        path.relative_to(source_root).as_posix()
        for path in (source_root / "content").rglob("*")
        if path.is_file()
    }
    if available != CONTENT_FILES:
        raise RuntimeError(f"Packaged content directory does not match manifest: {sorted(available)}")
    for relative_name in CONTENT_FILES:
        source = source_root / relative_name
        target = target_root / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return target_root


def prepare_project_metadata(stage: Path, build_root: Path) -> None:
    licenses = stage / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    for filename in ("LICENSE", "NOTICE.md"):
        shutil.copy2(ROOT / filename, licenses / filename)
    version_file = build_root / "version_info.txt"
    version_tuple = APP_VERSION.split(".")
    version_file.write_text(
        "# UTF-8\n"
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers=({', '.join(version_tuple)}, 0), "
        f"prodvers=({', '.join(version_tuple)}, 0), mask=0x3f, flags=0x0, "
        "OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040904B0', ["
        "StringStruct('CompanyName', 'NingYan678'), "
        "StringStruct('FileDescription', 'Ameath Desktop Pet'), "
        f"StringStruct('FileVersion', '{APP_VERSION}'), "
        "StringStruct('InternalName', 'Ameath'), "
        "StringStruct('OriginalFilename', 'Ameath.exe'), "
        "StringStruct('ProductName', 'Ameath Desktop Pet'), "
        f"StringStruct('ProductVersion', '{APP_VERSION}')])])],\n"
        "  )\n",
        encoding="utf-8",
    )


def prepare_platform(stage: Path) -> Path:
    """Copy the bundled Hermes plugin without local caches or bytecode."""
    source = ROOT / "hermes_platform"
    target = stage / "hermes_platform"
    remove_tree(target)
    shutil.copytree(source, target, ignore=ignore_source)
    return target


def build_frontend(stage: Path, build_root: Path) -> None:
    app, dist, work = stage / "app", build_root / "pyinstaller", build_root / "pyinstaller-work"
    for path in (app, dist, work):
        remove_tree(path)
    separator = ";" if os.name == "nt" else ":"
    prepare_project_metadata(stage, build_root)
    platform_root = prepare_platform(stage)
    run(
        "uv", "run", "--with", "pyinstaller==6.14.2",
        "--with", "PySide6>=6.7,<7", "--with", "python-dotenv>=1.0,<2",
        "pyinstaller", "--noconfirm", "--clean", "--windowed", "--name", "Ameath",
        "--paths", str(ROOT / "src"),
        "--icon", str(ROOT / "assets" / "recovered" / "gifs" / "ameath.ico"),
        "--version-file", str(build_root / "version_info.txt"),
        "--add-data", f"{prepare_assets(stage)}{separator}assets",
        "--add-data", f"{platform_root}{separator}hermes_platform",
        "--add-data", f"{ROOT / 'VERSION'}{separator}.",
        "--distpath", str(dist), "--workpath", str(work), "--specpath", str(build_root), str(ROOT / "packaging" / "ameath_entry.py"),
    )
    shutil.copytree(dist / "Ameath", app)


def build_runtime(stage: Path, hermes_source: Path, python_version: str) -> Path:
    runtime = stage / "runtime"
    remove_tree(runtime)
    source_target = runtime / "hermes-agent"
    shutil.copytree(hermes_source, source_target, ignore=ignore_source)
    python_root = runtime / "python"
    python_environment = os.environ.copy()
    python_environment["UV_PYTHON_INSTALL_DIR"] = str(python_root)
    run("uv", "python", "install", "--install-dir", str(python_root), "--no-bin", "--no-registry", python_version, env=python_environment)
    interpreters = tuple(python_root.glob("*/python.exe"))
    if not interpreters:
        raise RuntimeError("uv did not create a portable Python interpreter in the release staging directory")
    interpreter = max(interpreters, key=lambda candidate: candidate.stat().st_mtime_ns).resolve()
    if not interpreter.is_file() or not interpreter.is_relative_to(runtime.resolve()):
        raise RuntimeError("uv did not install a portable Python inside the release staging directory")
    # Hermes intentionally blocks wheel builds; the shipped source tree is the
    # runtime, so an editable install is the supported production layout here.
    run(
        "uv", "pip", "install", "--break-system-packages", "--link-mode", "copy", "--python", str(interpreter),
        "-e", str(source_target), "aiohttp==3.14.1", "pip",
    )
    prefix = Path(subprocess.check_output([str(interpreter), "-c", "import sys; print(sys.prefix)"], text=True).strip()).resolve()
    if not prefix.is_relative_to(runtime.resolve()):
        raise RuntimeError("staged Hermes Python resolved outside the release staging directory")
    hermes_module = Path(subprocess.check_output([str(interpreter), "-c", "import hermes_cli; print(hermes_cli.__file__)"], text=True).strip()).resolve()
    if not hermes_module.is_relative_to(runtime.resolve()):
        raise RuntimeError("staged Hermes source resolved outside the release staging directory")
    (runtime / "runtime_metadata.json").write_text(
        json.dumps(
            {
                "python_relative_path": interpreter.relative_to(runtime).as_posix(),
                "hermes_commit": BUNDLED_HERMES_COMMIT,
                "bundled_hermes_commit": BUNDLED_HERMES_COMMIT,
                "python_version": python_version,
                "source_url": "https://github.com/NousResearch/hermes-agent.git",
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    license_path = hermes_source / "LICENSE"
    if license_path.is_file():
        licenses = stage / "licenses"
        licenses.mkdir(exist_ok=True)
        shutil.copy2(license_path, licenses / "Hermes-MIT.txt")
    return runtime


def archive_runtime(runtime: Path, build_root: Path) -> Path:
    archive_base = build_root / "Ameath-Hermes-runtime"
    archive = archive_base.with_suffix(".zip")
    archive.unlink(missing_ok=True)
    shutil.make_archive(str(archive_base), "zip", runtime.parent, runtime.name)
    return archive


def compile_installer(stage: Path) -> None:
    user_iscc = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"
    iscc = shutil.which("ISCC.exe") or shutil.which("ISCC") or (str(user_iscc) if user_iscc.is_file() else None)
    if not iscc:
        raise RuntimeError("Inno Setup 6 is required. Install it, then rerun this build command.")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    run(iscc, f"/DAppVersion={APP_VERSION}", f"/DStageDir={stage}", f"/O{output}", str(ROOT / "packaging" / "Ameath.iss"))


def sign_artifact(path: Path) -> bool:
    """Sign when CI provides a PFX; unsigned local builds remain supported."""
    certificate = os.getenv("AMEATH_SIGN_CERT", "").strip()
    if not certificate:
        print(f"Unsigned artifact (no AMEATH_SIGN_CERT): {path.name}")
        return False
    signtool = shutil.which("signtool.exe") or shutil.which("signtool")
    if not signtool:
        raise RuntimeError("AMEATH_SIGN_CERT is set but signtool.exe was not found.")
    command = [signtool, "sign", "/fd", "SHA256", "/f", certificate]
    password = os.getenv("AMEATH_SIGN_PASSWORD", "")
    if password:
        command.extend(["/p", password])
    timestamp = os.getenv("AMEATH_TIMESTAMP_URL", "http://timestamp.digicert.com").strip()
    if timestamp:
        command.extend(["/tr", timestamp, "/td", "SHA256"])
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, text=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-source", type=Path, default=Path(r"D:\hermes\hermes-agent"))
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--skip-installer", action="store_true")
    parser.add_argument("--keep-build", action="store_true", help="keep temporary release work under build/installer for diagnosis")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("Windows is required to build Windows installers.")
    if not (args.hermes_source / "hermes_cli" / "main.py").is_file():
        raise RuntimeError("--hermes-source must point to a Hermes source checkout.")
    try:
        commit = subprocess.check_output(["git", "-C", str(args.hermes_source), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(args.hermes_source), "status", "--porcelain", "--untracked-files=all"],
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("--hermes-source must be a Git checkout pinned to the required Hermes commit.") from exc
    if commit != BUNDLED_HERMES_COMMIT:
        raise RuntimeError(
            f"--hermes-source is {commit}, expected bundled Hermes baseline {BUNDLED_HERMES_COMMIT}."
        )
    if dirty:
        raise RuntimeError("--hermes-source must have a clean working tree for a reproducible build.")
    build_root = ROOT / "build" / "installer" if args.keep_build else Path(tempfile.mkdtemp(prefix="ameath-release-"))
    if args.keep_build:
        remove_tree(build_root)
        build_root.mkdir(parents=True)
    try:
        stage = build_root / "offline"
        stage.mkdir(parents=True)
        build_frontend(stage, build_root)
        archive = archive_runtime(build_runtime(stage, args.hermes_source, args.python), build_root)
        print(f"Offline runtime: {archive} ({sha256(archive)})")
        if os.getenv("AMEATH_SIGN_CERT"):
            sign_artifact(stage / "app" / "Ameath.exe")
        if not args.skip_installer:
            compile_installer(stage)
            installer = ROOT / "dist" / f"Ameath-{APP_VERSION}-offline-setup.exe"
            if installer.is_file() and os.getenv("AMEATH_SIGN_CERT"):
                sign_artifact(installer)
            if installer.is_file():
                write_checksum(installer)
    finally:
        if not args.keep_build:
            remove_tree(build_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
