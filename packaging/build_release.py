"""Build personal online and offline Windows installers for Ameath.

Run on Windows from a checkout that has a known Hermes source tree. The script
refuses to create an online installer without a checksum-pinned runtime URL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "installer"
HERMES_COMMIT = "8fc278207b0f5b25e567966f9615e1b1737f62af"
APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", APP_VERSION) is None:
    raise RuntimeError("VERSION must contain a valid SemVer value")
SKIP_SOURCE_NAMES = {".git", ".github", ".plans", "tests", "tests-js", "docs", "website", "node_modules", "venv", "__pycache__"}


def run(*command: str, cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


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


def ignore_source(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_SOURCE_NAMES or name.endswith(".pyc")}


def build_frontend(stage: Path) -> None:
    app, dist, work = stage / "app", BUILD / "pyinstaller", BUILD / "pyinstaller-work"
    for path in (app, dist, work):
        remove_tree(path)
    separator = ";" if os.name == "nt" else ":"
    run(
        "uv", "run", "--with", "pyinstaller==6.14.2",
        "--with", "PySide6>=6.7,<7", "--with", "httpx>=0.27,<1", "--with", "python-dotenv>=1.0,<2",
        "pyinstaller", "--noconfirm", "--clean", "--windowed", "--name", "Ameath",
        "--paths", str(ROOT / "src"),
        "--add-data", f"{ROOT / 'assets'}{separator}assets",
        "--add-data", f"{ROOT / 'hermes_platform'}{separator}hermes_platform",
        "--add-data", f"{ROOT / 'VERSION'}{separator}.",
        "--distpath", str(dist), "--workpath", str(work), "--specpath", str(BUILD), str(ROOT / "packaging" / "ameath_entry.py"),
    )
    shutil.copytree(dist / "Ameath", app)


def build_runtime(stage: Path, hermes_source: Path, python_version: str) -> Path:
    runtime = stage / "runtime"
    remove_tree(runtime)
    source_target = runtime / "hermes-agent"
    shutil.copytree(hermes_source, source_target, ignore=ignore_source)
    # A clean CPython is used instead of copying a development venv.
    run("uv", "python", "install", python_version)
    interpreter = subprocess.check_output(["uv", "python", "find", python_version], text=True).strip()
    shutil.copytree(Path(interpreter).resolve().parent, runtime / "python")
    # uv-managed CPython carries the PEP 668 marker. This is a copied release
    # runtime, not the build machine's interpreter, so it is safe to populate.
    # Hermes intentionally blocks wheel builds; the shipped source tree is the
    # runtime, so an editable install is the supported production layout here.
    run(
        "uv", "pip", "install", "--break-system-packages", "--python", str(runtime / "python" / "python.exe"),
        "-e", str(source_target), "aiohttp==3.14.1",
    )
    license_path = hermes_source / "LICENSE"
    if license_path.is_file():
        licenses = stage / "licenses"
        licenses.mkdir(exist_ok=True)
        shutil.copy2(license_path, licenses / "Hermes-MIT.txt")
    return runtime


def archive_runtime(runtime: Path) -> Path:
    archive_base = BUILD / "Ameath-Hermes-runtime"
    archive = archive_base.with_suffix(".zip")
    archive.unlink(missing_ok=True)
    shutil.make_archive(str(archive_base), "zip", runtime.parent, runtime.name)
    return archive


def make_online_runtime(stage: Path, runtime_url: str, runtime_sha256: str) -> None:
    runtime = stage / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "runtime_manifest.json").write_text(
        json.dumps({"url": runtime_url, "sha256": runtime_sha256, "hermes_commit": HERMES_COMMIT}, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(ROOT / "packaging" / "runtime-bootstrap.ps1", runtime / "runtime-bootstrap.ps1")


def compile_installer(mode: str, stage: Path) -> None:
    user_iscc = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"
    iscc = shutil.which("ISCC.exe") or shutil.which("ISCC") or (str(user_iscc) if user_iscc.is_file() else None)
    if not iscc:
        raise RuntimeError("Inno Setup 6 is required. Install it, then rerun this build command.")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    run(iscc, f"/DAppVersion={APP_VERSION}", f"/DBuildMode={mode}", f"/DStageDir={stage}", f"/O{output}", str(ROOT / "packaging" / "Ameath.iss"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("online", "offline", "all"), default="all")
    parser.add_argument("--hermes-source", type=Path, default=Path(r"D:\hermes\hermes-agent"))
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--runtime-url", default="")
    parser.add_argument("--runtime-sha256", default="")
    parser.add_argument("--skip-installer", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("Windows is required to build Windows installers.")
    if not (args.hermes_source / "hermes_cli" / "main.py").is_file():
        raise RuntimeError("--hermes-source must point to a Hermes source checkout.")
    modes = ("online", "offline") if args.mode == "all" else (args.mode,)
    for mode in modes:
        stage = BUILD / mode
        remove_tree(stage)
        stage.mkdir(parents=True)
        build_frontend(stage)
        if mode == "offline":
            archive = archive_runtime(build_runtime(stage, args.hermes_source, args.python))
            print(f"Offline runtime: {archive} ({sha256(archive)})")
        else:
            if not args.runtime_url or not args.runtime_sha256:
                raise RuntimeError("Online builds require --runtime-url and --runtime-sha256 from the offline runtime archive.")
            make_online_runtime(stage, args.runtime_url, args.runtime_sha256)
        if not args.skip_installer:
            compile_installer(mode, stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
