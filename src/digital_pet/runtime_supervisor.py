"""Non-blocking Gateway supervision for shared and isolated Hermes runtimes."""

from __future__ import annotations

import logging
from typing import Protocol

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, QTimer, Signal

from .runtime_descriptor import RuntimeHealth

LOGGER = logging.getLogger("digital_pet.runtime")


class RuntimeBackend(Protocol):
    def quick_health(self) -> RuntimeHealth: ...
    def verify_identity(self) -> RuntimeHealth: ...
    def start_gateway(self) -> bool: ...


class _VerificationSignals(QObject):
    finished = Signal(object)


class _VerificationTask(QRunnable):
    def __init__(self, runtime: RuntimeBackend) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.runtime = runtime
        self.signals = _VerificationSignals(QCoreApplication.instance())

    def run(self) -> None:
        try:
            result = self.runtime.verify_identity()
        except (OSError, RuntimeError):
            LOGGER.exception("Gateway identity verification failed")
            result = RuntimeHealth.ERROR
        self.signals.finished.emit(result)


class RuntimeSupervisor(QObject):
    """Polls only native descriptor/PID state; WMI verification is background-only."""

    status_changed = Signal(str)
    connection_allowed = Signal(bool)

    def __init__(self, runtime: RuntimeBackend, *, shared: bool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.shared = shared
        self._attempt = 0
        self._verification_active = False
        self._verification_task: _VerificationTask | None = None
        self._connection_allowed = False
        self._maintenance = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check)

    def start(self) -> None:
        self._attempt = 0
        self._timer.start(50)

    def stop(self) -> None:
        self._timer.stop()

    def reconnect_now(self) -> None:
        if self._maintenance:
            return
        self._attempt = 0
        self._check()

    def set_maintenance(self, active: bool) -> None:
        """Suspend recovery while a controlled Hermes update owns the runtime."""
        self._maintenance = active
        self._timer.stop()
        self._set_connection_allowed(False)
        if active:
            self.status_changed.emit("Hermes 更新中…")
            return
        self._attempt = 0
        self._timer.start(50)

    def _set_connection_allowed(self, allowed: bool) -> None:
        if allowed != self._connection_allowed:
            self._connection_allowed = allowed
            self.connection_allowed.emit(allowed)

    def _check(self) -> None:
        if self._maintenance:
            return
        health = self.runtime.quick_health()
        if health is RuntimeHealth.READY:
            self._attempt = 0
            self._set_connection_allowed(True)
            self.status_changed.emit("已连接 Hermes Gateway")
            self._timer.start(10_000)
            return
        self._set_connection_allowed(False)
        if health is RuntimeHealth.VERIFYING:
            self.status_changed.emit("正在验证 Hermes Gateway…")
            self._verify_in_background()
            self._timer.start(10_000)
            return
        if health is RuntimeHealth.UNTRUSTED:
            self.status_changed.emit("Gateway 进程身份不匹配，已安全断开")
            self._timer.start(10_000)
            return
        if health is RuntimeHealth.ERROR:
            self.status_changed.emit("无法验证 Hermes Gateway，稍后重试")
            self._timer.start(10_000)
            return
        if self.shared:
            self.status_changed.emit("等待本机 Hermes Gateway")
            self._timer.start(10_000)
            return
        self._attempt += 1
        delay = min(60_000, 1_000 * (2 ** min(self._attempt, 6)))
        try:
            started = self.runtime.start_gateway()
        except (OSError, RuntimeError):
            LOGGER.exception("Failed to recover the Ameath-owned Hermes Gateway")
            started = False
        self.status_changed.emit("正在恢复 Hermes Gateway" if started else "Hermes Gateway 暂不可用")
        self._timer.start(delay)

    def _verify_in_background(self) -> None:
        if self._verification_active:
            return
        self._verification_active = True
        task = _VerificationTask(self.runtime)
        self._verification_task = task
        task.signals.finished.connect(self._verification_finished)
        QThreadPool.globalInstance().start(task)

    def _verification_finished(self, health: object) -> None:
        self._verification_active = False
        self._verification_task = None
        if health is RuntimeHealth.READY:
            self._check()
            return
        self._set_connection_allowed(False)
        if health is RuntimeHealth.UNTRUSTED:
            self.status_changed.emit("Gateway 进程身份不匹配，已安全断开")
        elif health is RuntimeHealth.STOPPED:
            self.status_changed.emit("Hermes Gateway 未运行")
        else:
            self.status_changed.emit("无法验证 Hermes Gateway，稍后重试")
