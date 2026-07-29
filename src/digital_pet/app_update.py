"""Explicit, verifiable Ameath application updates from the official release feed."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QTimer, Signal

from .background_task import FunctionTask, start_task
from .storage import atomic_write_json
from .version import APP_VERSION

OFFICIAL_REPOSITORY = "https://api.github.com/repos/NingYan678/ameath-desktop/releases/latest"
OFFICIAL_RELEASE_PAGE = "https://github.com/NingYan678/ameath-desktop/releases"
CHECK_INTERVAL = timedelta(hours=24)
RETRY_INTERVAL = timedelta(hours=6)
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_SEMVER = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class AppUpdateStatus(StrEnum):
    IDLE = "idle"
    CHECKING = "checking"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class AppUpdateInfo:
    current_version: str
    target_version: str
    download_url: str
    checksum_url: str
    release_url: str
    checked_at: str
    update_available: bool
    signed: bool = False


@dataclass(frozen=True)
class AppUpdateResult:
    version: str
    installer: Path
    sha256: str
    launched: bool = False


class AppUpdateStateStore:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "app_update_state.json"

    def load(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {key: str(value) for key, value in payload.items() if key in {"last_checked_at", "target_version", "notified_version", "retry_after", "last_error"}}

    def save(self, payload: dict[str, str]) -> None:
        atomic_write_json(self.path, payload)

    def check_due(self, now: datetime | None = None) -> bool:
        state = self.load()
        raw = state.get("retry_after") or state.get("last_checked_at")
        if not raw:
            return True
        try:
            checked = datetime.fromisoformat(raw)
        except ValueError:
            return True
        current = now or datetime.now(UTC)
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=UTC)
        interval = RETRY_INTERVAL if state.get("retry_after") else CHECK_INTERVAL
        return current - checked >= interval


class AppUpdateService:
    def __init__(
        self,
        data_root: Path,
        *,
        current_version: str = APP_VERSION,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.current_version = current_version
        self.state_store = AppUpdateStateStore(data_root)
        self.download_root = data_root / "updates"
        self._opener = opener or urllib.request.urlopen

    def check(self) -> AppUpdateInfo:
        now = datetime.now(UTC)
        try:
            request = urllib.request.Request(OFFICIAL_REPOSITORY, headers={"Accept": "application/vnd.github+json", "User-Agent": "Ameath-Desktop"})
            with self._opener(request, timeout=20) as response:
                payload = json.loads(response.read())
            info = self._parse_release(payload, now)
            previous = self.state_store.load()
            previous.update({"last_checked_at": info.checked_at, "target_version": info.target_version})
            previous.pop("retry_after", None)
            previous.pop("last_error", None)
            self.state_store.save(previous)
            return info
        except (OSError, ValueError, TypeError, KeyError, URLError) as exc:
            previous = self.state_store.load()
            previous.update({"retry_after": (now + RETRY_INTERVAL).isoformat(), "last_error": str(exc)[:240]})
            self.state_store.save(previous)
            raise RuntimeError("暂时无法检查爱弥斯更新，请稍后重试。") from exc

    def download(self, info: AppUpdateInfo) -> AppUpdateResult:
        if not info.update_available or not self._official_asset(info.download_url, ".exe") or not self._official_asset(info.checksum_url, ".sha256"):
            raise RuntimeError("更新资产来源或版本不受信任。")
        self.download_root.mkdir(parents=True, exist_ok=True)
        target = self.download_root / f"Ameath-{info.target_version}-offline-setup.exe"
        part = target.with_suffix(target.suffix + ".part")
        self._download_limited(info.download_url, part)
        expected = self._read_checksum(info.checksum_url, target.name)
        actual = _sha256(part)
        if expected.lower() != actual.lower():
            part.unlink(missing_ok=True)
            raise RuntimeError("安装包 SHA-256 校验失败，已拒绝安装。")
        part.replace(target)
        return AppUpdateResult(info.target_version, target, actual)

    def launch_installer(self, result: AppUpdateResult) -> AppUpdateResult:
        if not result.installer.is_file():
            raise RuntimeError("安装包不存在，无法启动更新。")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([str(result.installer)], creationflags=flags)
        return AppUpdateResult(result.version, result.installer, result.sha256, launched=True)

    def _parse_release(self, payload: Any, now: datetime) -> AppUpdateInfo:
        if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
            return AppUpdateInfo(self.current_version, self.current_version, "", "", OFFICIAL_RELEASE_PAGE, now.isoformat(), False)
        tag = payload.get("tag_name")
        match = _SEMVER.fullmatch(str(tag or ""))
        if match is None:
            raise ValueError("release tag is not stable SemVer")
        target = ".".join(match.groups())
        if _version_tuple(target) <= _version_tuple(self.current_version):
            return AppUpdateInfo(self.current_version, target, "", "", str(payload.get("html_url") or OFFICIAL_RELEASE_PAGE), now.isoformat(), False)
        assets = payload.get("assets")
        if not isinstance(assets, list):
            raise ValueError("release assets are missing")
        exe_name = f"Ameath-{target}-offline-setup.exe"
        sha_name = exe_name + ".sha256"
        by_name = {item.get("name"): item for item in assets if isinstance(item, dict)}
        exe, checksum = by_name.get(exe_name), by_name.get(sha_name)
        if not isinstance(exe, dict) or not isinstance(checksum, dict):
            raise ValueError("release assets are incomplete")
        download_url, checksum_url = exe.get("browser_download_url"), checksum.get("browser_download_url")
        if not self._official_asset(download_url, ".exe") or not self._official_asset(checksum_url, ".sha256"):
            raise ValueError("release assets are not official GitHub HTTPS URLs")
        return AppUpdateInfo(self.current_version, target, download_url, checksum_url, str(payload.get("html_url") or OFFICIAL_RELEASE_PAGE), now.isoformat(), True)

    @staticmethod
    def _official_asset(url: object, suffix: str) -> bool:
        if not isinstance(url, str) or not url.startswith("https://") or not url.endswith(suffix):
            return False
        host = urlparse(url).hostname or ""
        return host == "github.com" or host.endswith(".github.com") or host.endswith("githubusercontent.com")

    def _download_limited(self, url: str, target: Path) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "Ameath-Desktop"})
        with self._opener(request, timeout=60) as response, target.open("wb") as output:
            final_url = getattr(response, "geturl", lambda: url)()
            if not self._official_asset(final_url, ".exe"):
                raise RuntimeError("下载被重定向到非 GitHub 资产域。")
            length = int(response.headers.get("Content-Length", "0") or 0)
            if length > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("安装包超过 512 MB 限制。")
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("安装包超过 512 MB 限制。")
                output.write(block)

    def _read_checksum(self, url: str, filename: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "Ameath-Desktop"})
        with self._opener(request, timeout=20) as response:
            final_url = getattr(response, "geturl", lambda: url)()
            if not self._official_asset(final_url, ".sha256"):
                raise RuntimeError("校验文件被重定向到非 GitHub 资产域。")
            text = response.read(32_000).decode("utf-8", errors="replace")
        match = re.search(rf"\b([0-9a-fA-F]{{64}})\b(?:\s+\*?{re.escape(filename)})?", text)
        if match is None:
            raise RuntimeError("校验文件格式无效。")
        return match.group(1)


class AppUpdateController(QObject):
    state_changed = Signal(str)
    info_changed = Signal(object)
    update_available = Signal(object)
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, service: AppUpdateService, *, install_allowed: Callable[[], bool], auto_check: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._install_allowed = install_allowed
        self._auto_check = auto_check
        self._suspended = False
        self._info: AppUpdateInfo | None = None
        self._task: FunctionTask | None = None
        self._state = AppUpdateStatus.IDLE
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.check(silent=True))

    @property
    def state(self) -> AppUpdateStatus:
        return self._state

    @property
    def info(self) -> AppUpdateInfo | None:
        return self._info

    @property
    def busy(self) -> bool:
        return self._task is not None

    def set_suspended(self, suspended: bool) -> None:
        self._suspended = suspended
        if suspended:
            self._timer.stop()

    def set_auto_check(self, enabled: bool) -> None:
        self._auto_check = enabled
        if not enabled:
            self._timer.stop()

    def start(self) -> None:
        if self._auto_check and not self._suspended and not self._timer.isActive():
            self._timer.start(90_000 if not self.service.state_store.load().get("last_checked_at") else int(CHECK_INTERVAL.total_seconds() * 1_000))

    def check(self, *, silent: bool = False) -> bool:
        if self.busy or self._suspended:
            return False
        self._set_state(AppUpdateStatus.CHECKING)
        self._task = start_task(self.service.check, succeeded=self._checked, failed=lambda message: self._failed(message, silent))
        return True

    def apply(self) -> bool:
        if self.busy or self._info is None or not self._info.update_available or not self._install_allowed():
            return False
        self._set_state(AppUpdateStatus.DOWNLOADING)
        self._task = start_task(lambda: self.service.download(self._info), succeeded=self._downloaded, failed=self._failed)
        return True

    def launch_ready(self) -> bool:
        if self.busy or self._info is None:
            return False
        result = getattr(self, "_result", None)
        if not isinstance(result, AppUpdateResult):
            return False
        try:
            self._result = self.service.launch_installer(result)
        except RuntimeError as exc:
            self._failed(str(exc))
            return False
        self.ready.emit(self._result)
        return True

    def _checked(self, result: object) -> None:
        self._task = None
        self._info = result if isinstance(result, AppUpdateInfo) else None
        self._set_state(AppUpdateStatus.AVAILABLE if self._info and self._info.update_available else AppUpdateStatus.IDLE)
        if self._info is not None:
            self.info_changed.emit(self._info)
            state = self.service.state_store.load()
            if self._info.update_available and state.get("notified_version") != self._info.target_version:
                state["notified_version"] = self._info.target_version
                self.service.state_store.save(state)
                self.update_available.emit(self._info)
        self._schedule_next()

    def _downloaded(self, result: object) -> None:
        self._task = None
        if isinstance(result, AppUpdateResult):
            self._result = result
            self._set_state(AppUpdateStatus.READY)
            self.launch_ready()
        else:
            self._failed("更新下载结果无效。")

    def _failed(self, message: str, silent: bool = False) -> None:
        self._task = None
        self._set_state(AppUpdateStatus.FAILED)
        if not silent:
            self.failed.emit(message)
        self._schedule_next(retry=True)

    def _schedule_next(self, retry: bool = False) -> None:
        if self._auto_check and not self._suspended:
            self._timer.start(int((RETRY_INTERVAL if retry else CHECK_INTERVAL).total_seconds() * 1_000))

    def _set_state(self, state: AppUpdateStatus) -> None:
        self._state = state
        self.state_changed.emit(state.value)


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(version)
    if match is None:
        return (0, 0, 0)
    return tuple(int(value) for value in match.groups())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
