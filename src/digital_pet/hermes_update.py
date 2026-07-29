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
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from PySide6.QtCore import QObject, QTimer, Signal

from .background_task import FunctionTask, start_task
from .config import Settings, packaged_runtime_python
from .diagnostics import DiagnosticsService
from .runtime_descriptor import RuntimeHealth
from .storage import atomic_write_json


LOGGER = logging.getLogger("digital_pet.runtime")
OFFICIAL_REPOSITORY = "https://github.com/NousResearch/hermes-agent.git"
OFFICIAL_ARCHIVE = "https://github.com/NousResearch/hermes-agent/archive/{revision}.zip"
CHECK_INTERVAL = timedelta(hours=24)
OFFLINE_RETRY_INTERVAL = timedelta(hours=6)


class HermesUpdateStatus(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    AVAILABLE = "available"
    UPDATING = "updating"
    VERIFYING = "verifying"
    FAILED = "failed"


@dataclass(frozen=True)
class HermesUpdateInfo:
    current_revision: str
    target_revision: str
    source_url: str
    runtime_kind: str
    update_available: bool
    checked_at: str
    current_branch: str = ""


@dataclass(frozen=True)
class HermesUpdateResult:
    previous_revision: str
    current_revision: str
    updated: bool
    log_path: Path
    runtime_root: Path | None = None


@dataclass(frozen=True)
class HermesUpdateState:
    last_checked_at: str = ""
    retry_after: str = ""
    target_revision: str = ""
    notified_revision: str = ""
    last_error: str = ""


class UpdateRuntime(Protocol):
    settings: Settings

    def stop_gateway(self) -> bool: ...
    def switch_runtime(self, runtime_root: Path) -> None: ...
    def prepare(self) -> None: ...
    def start_gateway(self) -> bool: ...
    def verify_identity(self) -> RuntimeHealth: ...


class HermesUpdateStateStore:
    """Persist non-secret scheduling and notification state."""

    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "hermes_update_state.json"

    def load(self) -> HermesUpdateState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            return HermesUpdateState(
                last_checked_at=str(payload.get("last_checked_at", "")),
                retry_after=str(payload.get("retry_after", "")),
                target_revision=str(payload.get("target_revision", "")),
                notified_revision=str(payload.get("notified_revision", "")),
                last_error=str(payload.get("last_error", "")),
            )
        except (OSError, ValueError, TypeError):
            return HermesUpdateState()

    def save(self, state: HermesUpdateState) -> None:
        atomic_write_json(self.path, asdict(state))

    def check_due(self, now: datetime | None = None) -> bool:
        state = self.load()
        current = now or datetime.now(timezone.utc)
        retry = _parse_time(state.retry_after)
        checked = _parse_time(state.last_checked_at)
        if retry is not None:
            return current >= retry
        return checked is None or current - checked >= CHECK_INTERVAL


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
        now = datetime.now(timezone.utc)
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
            return self._apply_shared(info, log_path)
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

    def _apply_shared(self, info: HermesUpdateInfo, log_path: Path) -> HermesUpdateResult:
        branch, _ = self.shared_preflight()
        original_revision = info.current_revision
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
            raise
        self._write_log(log_path, command, result.stdout, result.stderr)
        if result.returncode:
            self._restore_shared_revision(branch, original_revision, log_path)
            raise RuntimeError(f"Hermes 更新失败（退出码 {result.returncode}）。详情见：{log_path}")
        self._report_progress(HermesUpdateStatus.VERIFYING)
        current = self.current_revision()
        if current != info.target_revision:
            self._restore_shared_revision(branch, original_revision, log_path)
            raise RuntimeError(f"Hermes 更新结束，但版本验证失败。更新前分支：{branch or '(detached)'}；详情见：{log_path}")
        return HermesUpdateResult(info.current_revision, current, True, log_path)

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


class HermesUpdateController(QObject):
    """Own update tasks so closing the settings dialog cannot orphan them."""

    state_changed = Signal(str)
    info_changed = Signal(object)
    update_available = Signal(object)
    completed = Signal(object)
    failed = Signal(str)
    _progress_requested = Signal(object)

    def __init__(
        self,
        service: HermesUpdateService,
        runtime: UpdateRuntime,
        *,
        maintenance: Callable[[bool], None],
        install_allowed: Callable[[], bool],
        auto_check: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.runtime = runtime
        self._maintenance = maintenance
        self._install_allowed = install_allowed
        self._auto_check = auto_check
        self._gateway_ready = False
        self._state = HermesUpdateStatus.IDLE
        self._info: HermesUpdateInfo | None = None
        self._task: FunctionTask | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._automatic_check)
        self._progress_requested.connect(self._progress_changed)
        self.service.progress = self._progress_requested.emit

    @property
    def state(self) -> HermesUpdateStatus:
        return self._state

    @property
    def info(self) -> HermesUpdateInfo | None:
        return self._info

    @property
    def busy(self) -> bool:
        return self._task is not None or self._state in {
            HermesUpdateStatus.CHECKING,
            HermesUpdateStatus.UPDATING,
            HermesUpdateStatus.VERIFYING,
        }

    def set_auto_check(self, enabled: bool) -> None:
        self._auto_check = enabled
        if enabled and self._gateway_ready and not self._timer.isActive():
            self._timer.start(60_000)
        elif not enabled:
            self._timer.stop()

    def gateway_ready(self) -> None:
        self._gateway_ready = True
        if self._auto_check and not self._timer.isActive():
            self._timer.start(60_000)

    def check(self, *, silent: bool = False) -> bool:
        if self.busy:
            return False
        self._set_state(HermesUpdateStatus.CHECKING)
        task = start_task(
            self.service.check,
            succeeded=self._checked,
            failed=(lambda message: self._check_failed(message, silent)),
        )
        self._task = task
        return True

    def apply(self) -> bool:
        if self.busy or self._info is None or not self._info.update_available:
            return False
        if not self._install_allowed():
            self.failed.emit("Hermes 正在处理消息或等待确认，请完成后再更新。")
            return False
        self._maintenance(True)
        self._set_state(HermesUpdateStatus.UPDATING)
        task = start_task(
            lambda: self.service.apply(self.runtime),
            succeeded=self._applied,
            failed=self._apply_failed,
        )
        self._task = task
        return True

    def _automatic_check(self) -> None:
        if self._auto_check and self.service.state_store.check_due():
            self.check(silent=True)
        elif self._auto_check:
            self._timer.start(60 * 60 * 1_000)

    def _checked(self, result: object) -> None:
        self._task = None
        self._info = result if isinstance(result, HermesUpdateInfo) else None
        state = HermesUpdateStatus.AVAILABLE if self._info and self._info.update_available else HermesUpdateStatus.IDLE
        self._set_state(state)
        if self._info is not None:
            self.info_changed.emit(self._info)
            stored = self.service.state_store.load()
            if self._info.update_available and stored.notified_revision != self._info.target_revision:
                self.service.state_store.save(
                    HermesUpdateState(
                        last_checked_at=stored.last_checked_at,
                        target_revision=stored.target_revision,
                        notified_revision=self._info.target_revision,
                    )
                )
                self.update_available.emit(self._info)
        if self._auto_check:
            self._timer.start(int(CHECK_INTERVAL.total_seconds() * 1_000))

    def _check_failed(self, message: str, silent: bool) -> None:
        self._task = None
        self._set_state(HermesUpdateStatus.FAILED)
        if not silent:
            self.failed.emit(message)
        if self._auto_check:
            self._timer.start(int(OFFLINE_RETRY_INTERVAL.total_seconds() * 1_000))

    def _applied(self, result: object) -> None:
        self._task = None
        self._maintenance(False)
        self._set_state(HermesUpdateStatus.IDLE)
        if isinstance(result, HermesUpdateResult):
            self._info = HermesUpdateInfo(
                result.current_revision,
                result.current_revision,
                OFFICIAL_REPOSITORY,
                self.service.runtime_kind,
                False,
                datetime.now(timezone.utc).isoformat(),
            )
            self.info_changed.emit(self._info)
            self.completed.emit(result)

    def _apply_failed(self, message: str) -> None:
        self._task = None
        self._maintenance(False)
        self._set_state(HermesUpdateStatus.FAILED)
        self.failed.emit(message)

    def _set_state(self, state: HermesUpdateStatus) -> None:
        self._state = state
        self.state_changed.emit(state.value)

    def _progress_changed(self, value: object) -> None:
        if isinstance(value, HermesUpdateStatus):
            self._set_state(value)


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _normalized_remote(value: str) -> str:
    normalized = value.strip().lower().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized.removeprefix("git@github.com:")
    return normalized
