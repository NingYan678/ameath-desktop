"""Safe, opt-in Hermes updates for shared and Ameath-owned runtimes."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings, packaged_runtime_python
from .diagnostics import DiagnosticsService
from .hermes_update_state import (
    OFFICIAL_ARCHIVE,
    OFFICIAL_REPOSITORY,
    OFFLINE_RETRY_INTERVAL,
    HermesUpdateInfo,
    HermesUpdateResult,
    HermesUpdateState,
    HermesUpdateStateStore,
    HermesUpdateStatus,
    UpdateRuntime,
)
from .runtime_descriptor import RuntimeHealth
from .storage import atomic_write_json

LOGGER = logging.getLogger("digital_pet.runtime")
class HermesUpdateService:
    """Blocking update operations; callers run them outside the UI thread."""

    def __init__(
        self,
        settings: Settings,
        *,
        shared: bool,
        state_store: HermesUpdateStateStore | None = None,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        download: Callable[[str, Path], None] | None = None,
        progress: Callable[[HermesUpdateStatus], None] | None = None,
    ) -> None:
        self.settings = settings
        self.shared = shared
        self.state_store = state_store or HermesUpdateStateStore(settings.data_root)
        self._run_command = run_command
        self._download = download or self._download_file
        self.progress = progress

    @property
    def runtime_kind(self) -> str:
        return "shared" if self.shared else "isolated"

    def current_revision(self) -> str:
        if self.shared:
            return self._git("rev-parse", "HEAD").strip()
        metadata = self.settings.hermes_runtime_root / "runtime_metadata.json"
        try:
            return str(json.loads(metadata.read_text(encoding="utf-8"))["hermes_commit"]).strip()
        except (OSError, ValueError, KeyError, TypeError):
            return ""

    def check(self) -> HermesUpdateInfo:
        now = datetime.now(UTC)
        try:
            current = self.current_revision()
            target = self._remote_revision()
            branch = self._git("branch", "--show-current").strip() if self.shared else ""
            info = HermesUpdateInfo(
                current_revision=current,
                target_revision=target,
                source_url=OFFICIAL_REPOSITORY,
                runtime_kind=self.runtime_kind,
                update_available=bool(current and target and current != target),
                checked_at=now.isoformat(),
                current_branch=branch,
            )
            previous = self.state_store.load()
            self.state_store.save(
                HermesUpdateState(
                    last_checked_at=info.checked_at,
                    target_revision=target,
                    notified_revision=previous.notified_revision,
                )
            )
            return info
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            previous = self.state_store.load()
            self.state_store.save(
                HermesUpdateState(
                    last_checked_at=previous.last_checked_at,
                    retry_after=(now + OFFLINE_RETRY_INTERVAL).isoformat(),
                    target_revision=previous.target_revision,
                    notified_revision=previous.notified_revision,
                    last_error=str(exc)[:300],
                )
            )
            raise RuntimeError("暂时无法检查 Hermes 更新，请稍后重试。") from exc

    def apply(self, runtime: UpdateRuntime) -> HermesUpdateResult:
        info = self.check()
        log_path = self._new_log_path()
        if not info.update_available:
            return HermesUpdateResult(info.current_revision, info.current_revision, False, log_path)
        if self.shared:
            return self._apply_shared(info, log_path, runtime)
        return self._apply_isolated(info, log_path, runtime)

    def shared_preflight(self) -> tuple[str, str]:
        if not self.shared:
            raise RuntimeError("当前不是共享 Hermes。")
        source = self.settings.hermes_source
        origin = self._git("remote", "get-url", "origin").strip()
        if _normalized_remote(origin) != _normalized_remote(OFFICIAL_REPOSITORY):
            raise RuntimeError("只允许由爱弥斯更新 Hermes 官方仓库；自定义 fork 请在 Hermes 中手动更新。")
        dirty = self._git("status", "--porcelain", "--untracked-files=all").strip()
        if dirty:
            raise RuntimeError("Hermes 工作区存在未提交修改。请先提交、暂存或放弃这些修改，再进行更新。")
        if not (source / ".git").exists():
            raise RuntimeError("共享 Hermes 不是可验证的 Git 工作区。")
        self._validate_shared_python()
        return self._git("branch", "--show-current").strip(), origin

    def _apply_shared(self, info: HermesUpdateInfo, log_path: Path, runtime: UpdateRuntime | object) -> HermesUpdateResult:
        branch, _ = self.shared_preflight()
        original_revision = info.current_revision
        gateway_was_running = self._stop_shared_gateway(runtime)
        environment = os.environ.copy()
        environment["HERMES_HOME"] = str(self.settings.hermes_home)
        command = [
            str(self.settings.hermes_cli_python),
            str(self.settings.hermes_cli_launcher),
            "update",
            "--yes",
            "--branch",
            "main",
        ]
        try:
            result = self._run_command(
                command,
                cwd=self.settings.hermes_source,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1_800,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except Exception:
            self._restore_shared_revision(branch, original_revision, log_path)
            self._restart_shared_gateway(runtime, gateway_was_running)
            raise
        self._write_log(log_path, command, result.stdout, result.stderr)
        if result.returncode:
            self._restore_shared_revision(branch, original_revision, log_path)
            self._restart_shared_gateway(runtime, gateway_was_running)
            raise RuntimeError(f"Hermes 更新失败（退出码 {result.returncode}）。详情见：{log_path}")
        self._report_progress(HermesUpdateStatus.VERIFYING)
        current = self.current_revision()
        if current != info.target_revision:
            self._restore_shared_revision(branch, original_revision, log_path)
            self._restart_shared_gateway(runtime, gateway_was_running)
            raise RuntimeError(f"Hermes 更新结束，但版本验证失败。更新前分支：{branch or '(detached)'}；详情见：{log_path}")
        self._restart_shared_gateway(runtime, gateway_was_running)
        return HermesUpdateResult(info.current_revision, current, True, log_path)

    @staticmethod
    def _stop_shared_gateway(runtime: object) -> bool:
        """Stop only a verified shared Gateway before replacing its executable."""
        health_reader = getattr(runtime, "quick_health", None)
        health = health_reader() if callable(health_reader) else None
        if health is RuntimeHealth.STOPPED:
            return False
        if health is RuntimeHealth.UNTRUSTED:
            raise RuntimeError("The shared Hermes Gateway identity is untrusted; update was cancelled.")
        stopper = getattr(runtime, "stop_gateway", None)
        if not callable(stopper):
            return False
        if not stopper():
            health = health_reader() if callable(health_reader) else None
            if health is RuntimeHealth.STOPPED:
                return False
            raise RuntimeError("The shared Hermes Gateway could not be stopped safely.")
        return True

    @staticmethod
    def _restart_shared_gateway(runtime: object, was_running: bool) -> None:
        if not was_running:
            return
        starter = getattr(runtime, "start_gateway", None)
        if not callable(starter) or not starter():
            raise RuntimeError("The shared Hermes Gateway could not be restarted after the update.")

    def _validate_shared_python(self) -> None:
        """Reject known-broken venvs before the upstream updater can mutate Git."""
        interpreter = self.settings.hermes_cli_python
        if not interpreter.is_file():
            raise RuntimeError(f"Hermes Python interpreter was not found: {interpreter}")
        site_packages = interpreter.parent.parent / "Lib" / "site-packages"
        if not site_packages.is_dir():
            return
        invalid: list[str] = []
        for metadata in site_packages.glob("*.dist-info"):
            metadata_file = metadata / "METADATA"
            if not metadata_file.is_file():
                invalid.append(metadata.name)
                continue
            try:
                with metadata_file.open(encoding="utf-8", errors="replace") as stream:
                    first_line = stream.readline()
            except OSError:
                invalid.append(metadata.name)
                continue
            if not first_line.lower().startswith("metadata-version:") or not first_line.split(":", 1)[1].strip():
                invalid.append(metadata.name)
        invalid.extend(entry.name for entry in site_packages.iterdir() if entry.name.startswith("~"))
        if invalid:
            sample = ", ".join(sorted(invalid)[:4])
            raise RuntimeError(f"Hermes virtual environment has invalid package metadata: {sample}")

    def _restore_shared_revision(self, branch: str, revision: str, log_path: Path) -> None:
        """Restore the exact pre-update branch and commit after an updater failure."""
        if branch:
            self._git("switch", "--discard-changes", branch)
        else:
            self._git("switch", "--detach", "--discard-changes", revision)
        self._git("reset", "--hard", revision)
        self._git("clean", "-fd")
        with log_path.open("a", encoding="utf-8") as output:
            output.write(f"\n[rollback] restored {branch or '(detached)'} at {revision}\n")

    def _apply_isolated(
        self,
        info: HermesUpdateInfo,
        log_path: Path,
        runtime: UpdateRuntime,
    ) -> HermesUpdateResult:
        old_settings = runtime.settings
        old_root = old_settings.hermes_runtime_root
        slot = self._prepare_slot(info.target_revision, old_root, log_path)
        self._report_progress(HermesUpdateStatus.VERIFYING)
        if not runtime.stop_gateway():
            shutil.rmtree(slot, ignore_errors=True)
            raise RuntimeError("无法验证并停止爱弥斯专属 Gateway，更新已取消。")
        try:
            runtime.switch_runtime(slot)
            runtime.prepare()
            if not runtime.start_gateway() or not self._wait_until_ready(runtime):
                raise RuntimeError("新版 Hermes Gateway 未能通过启动验证。")
            atomic_write_json(
                self.settings.data_root / "runtime_current.json",
                {"hermes_commit": info.target_revision},
            )
        except Exception:
            LOGGER.exception("Rolling back failed isolated Hermes update")
            runtime.stop_gateway()
            runtime.switch_runtime(old_root)
            runtime.prepare()
            runtime.start_gateway()
            shutil.rmtree(slot, ignore_errors=True)
            raise
        self.settings = runtime.settings
        self._retain_runtime_slots(slot, old_root)
        return HermesUpdateResult(info.current_revision, info.target_revision, True, log_path, slot)

    def _prepare_slot(self, revision: str, source_runtime: Path, log_path: Path) -> Path:
        slots_root = self.settings.data_root / "runtimes"
        slots_root.mkdir(parents=True, exist_ok=True)
        target = slots_root / revision
        if self._valid_slot(target, revision):
            return target
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()
        marker = target / ".incomplete"
        marker.touch()
        try:
            shutil.copytree(source_runtime / "python", target / "python")
            archive = target / "hermes.zip"
            self._download(OFFICIAL_ARCHIVE.format(revision=revision), archive)
            source = target / "hermes-agent"
            self._extract_source(archive, source)
            archive.unlink(missing_ok=True)
            source_metadata = json.loads((source_runtime / "runtime_metadata.json").read_text(encoding="utf-8"))
            interpreter_relative = str(source_metadata["python_relative_path"])
            atomic_write_json(
                target / "runtime_metadata.json",
                {
                    "python_relative_path": interpreter_relative,
                    "hermes_commit": revision,
                    "python_version": str(source_metadata.get("python_version", "")),
                    "source_url": OFFICIAL_REPOSITORY,
                },
            )
            interpreter = packaged_runtime_python(target)
            bootstrap = [
                str(interpreter),
                "-m",
                "ensurepip",
                "--upgrade",
            ]
            bootstrapped = self._run_command(
                bootstrap,
                cwd=source,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            self._write_log(log_path, bootstrap, bootstrapped.stdout, bootstrapped.stderr)
            if bootstrapped.returncode:
                raise RuntimeError(f"无法准备 Hermes 更新所需的 pip。详情见：{log_path}")
            command = [
                str(interpreter),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--break-system-packages",
                "-e",
                str(source),
            ]
            result = self._run_command(
                command,
                cwd=source,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1_800,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            self._write_log(log_path, command, result.stdout, result.stderr)
            if result.returncode:
                raise RuntimeError(f"新版 Hermes 依赖安装失败。详情见：{log_path}")
            probe = self._run_command(
                [
                    str(interpreter),
                    "-c",
                    "import aiohttp, gateway.config, gateway.platforms.base, hermes_cli; print('ok')",
                ],
                cwd=source,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if probe.returncode or probe.stdout.strip() != "ok":
                raise RuntimeError("新版 Hermes 核心模块兼容性验证失败。")
            marker.unlink()
            return target
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    @staticmethod
    def _extract_source(archive: Path, target: Path) -> None:
        with tempfile.TemporaryDirectory(prefix="ameath-hermes-source-") as temporary:
            temporary_root = Path(temporary).resolve()
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    destination = (temporary_root / member.filename).resolve()
                    if not destination.is_relative_to(temporary_root):
                        raise RuntimeError("Hermes 更新包包含不安全路径。")
                bundle.extractall(temporary_root)
            roots = [path for path in temporary_root.iterdir() if path.is_dir()]
            if len(roots) != 1 or not (roots[0] / "hermes_cli" / "main.py").is_file():
                raise RuntimeError("Hermes 更新包结构无效。")
            shutil.copytree(roots[0], target)

    @staticmethod
    def _valid_slot(slot: Path, revision: str) -> bool:
        if (slot / ".incomplete").exists():
            return False
        try:
            metadata = json.loads((slot / "runtime_metadata.json").read_text(encoding="utf-8"))
            return (
                str(metadata.get("hermes_commit", "")) == revision
                and packaged_runtime_python(slot).is_file()
                and (slot / "hermes-agent" / "hermes_cli" / "main.py").is_file()
            )
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def _wait_until_ready(runtime: UpdateRuntime, timeout: float = 45.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if runtime.verify_identity() is RuntimeHealth.READY:
                return True
            time.sleep(0.5)
        return False

    def _retain_runtime_slots(self, current: Path, previous: Path) -> None:
        slots = self.settings.data_root / "runtimes"
        if not slots.is_dir():
            return
        retained = {current.resolve()}
        if previous.is_relative_to(slots):
            retained.add(previous.resolve())
        for candidate in slots.iterdir():
            if candidate.is_dir() and candidate.resolve() not in retained:
                shutil.rmtree(candidate, ignore_errors=True)

    def _remote_revision(self) -> str:
        result = self._run_command(
            ["git", "ls-remote", OFFICIAL_REPOSITORY, "refs/heads/main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if result.returncode:
            raise RuntimeError("无法读取 Hermes 官方版本。")
        revision = result.stdout.split(maxsplit=1)[0].strip().lower()
        if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
            raise RuntimeError("Hermes 官方版本信息无效。")
        return revision

    def _git(self, *arguments: str) -> str:
        result = self._run_command(
            ["git", "-C", str(self.settings.hermes_source), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"无法验证共享 Hermes Git 状态：{' '.join(arguments)}")
        return result.stdout

    def _new_log_path(self) -> Path:
        log_dir = self.settings.data_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"hermes-update-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.log"

    def _report_progress(self, status: HermesUpdateStatus) -> None:
        if self.progress is not None:
            self.progress(status)

    @staticmethod
    def _write_log(log_path: Path, command: list[str], stdout: str, stderr: str) -> None:
        safe = DiagnosticsService.redact(
            "$ " + " ".join(command) + "\n\n" + stdout + ("\n\n[stderr]\n" + stderr if stderr else "")
        )
        with log_path.open("a", encoding="utf-8") as output:
            output.write(safe)
            output.write("\n\n")

    @staticmethod
    def _download_file(url: str, destination: Path) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "Ameath-Hermes-Updater"})
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
            if response.geturl().split("?", 1)[0].lower().startswith("http://"):
                raise RuntimeError("Hermes 更新下载被降级到不安全连接。")
            shutil.copyfileobj(response, output)


def _normalized_remote(value: str) -> str:
    normalized = value.strip().lower().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized.removeprefix("git@github.com:")
    return normalized


# Compatibility export: callers continue importing the controller from this
# module while the Qt orchestration lives in its own file.
from .hermes_update_controller import HermesUpdateController  # noqa: F401,E402
