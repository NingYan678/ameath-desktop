"""Small Qt worker wrapper for blocking local and network operations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


LOGGER = logging.getLogger("digital_pet.runtime")


class TaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class FunctionTask(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            self.signals.succeeded.emit(self.operation())
        except (OSError, RuntimeError, ValueError) as exc:
            self.signals.failed.emit(str(exc))
        except Exception:
            LOGGER.exception("Unexpected background task failure")
            self.signals.failed.emit("后台操作失败，请查看诊断日志。")
        finally:
            self.signals.finished.emit()


def start_task(operation: Callable[[], Any]) -> FunctionTask:
    task = FunctionTask(operation)
    QThreadPool.globalInstance().start(task)
    return task
