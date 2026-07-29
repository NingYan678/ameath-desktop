"""Qt orchestration for background Hermes update checks and installs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from PySide6.QtCore import QObject, QTimer, Signal

from .background_task import FunctionTask, start_task
from .hermes_update import HermesUpdateService
from .hermes_update_state import (
    CHECK_INTERVAL,
    OFFICIAL_REPOSITORY,
    OFFLINE_RETRY_INTERVAL,
    HermesUpdateInfo,
    HermesUpdateResult,
    HermesUpdateState,
    HermesUpdateStatus,
    UpdateRuntime,
)


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
        self._suspended = False
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

    def set_suspended(self, suspended: bool) -> None:
        self._suspended = suspended
        if suspended:
            self._timer.stop()
        elif self._auto_check and self._gateway_ready and not self._timer.isActive():
            self._timer.start(60_000)

    def gateway_ready(self) -> None:
        self._gateway_ready = True
        if self._auto_check and not self._suspended and not self._timer.isActive():
            self._timer.start(60_000)

    def check(self, *, silent: bool = False) -> bool:
        if self.busy or self._suspended:
            return False
        self._set_state(HermesUpdateStatus.CHECKING)
        self._task = start_task(
            self.service.check,
            succeeded=self._checked,
            failed=lambda message: self._check_failed(message, silent),
        )
        return True

    def apply(self) -> bool:
        if self.busy or self._suspended or self._info is None or not self._info.update_available:
            return False
        if not self._install_allowed():
            self.failed.emit("Hermes 正在处理消息或等待确认，请完成后再更新。")
            return False
        self._maintenance(True)
        self._set_state(HermesUpdateStatus.UPDATING)
        self._task = start_task(
            lambda: self.service.apply(self.runtime),
            succeeded=self._applied,
            failed=self._apply_failed,
        )
        return True

    def _automatic_check(self) -> None:
        if self._auto_check and not self._suspended and self.service.state_store.check_due():
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
        if self._auto_check and not self._suspended:
            self._timer.start(int(CHECK_INTERVAL.total_seconds() * 1_000))

    def _check_failed(self, message: str, silent: bool) -> None:
        self._task = None
        self._set_state(HermesUpdateStatus.FAILED)
        if not silent:
            self.failed.emit(message)
        if self._auto_check and not self._suspended:
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
                datetime.now(UTC).isoformat(),
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
