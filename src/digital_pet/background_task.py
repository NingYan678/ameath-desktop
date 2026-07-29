"""Small Qt worker wrapper for blocking local and network operations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Signal

LOGGER = logging.getLogger("digital_pet.runtime")


class TaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class FunctionTask(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.operation = operation
        self.signals = TaskSignals(QCoreApplication.instance())

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


def start_task(
    operation: Callable[[], Any],
    *,
    succeeded: Callable[[Any], None] | None = None,
    failed: Callable[[str], None] | None = None,
    finished: Callable[[], None] | None = None,
) -> FunctionTask:
    task = FunctionTask(operation)
    if succeeded is not None:
        task.signals.succeeded.connect(succeeded)
    if failed is not None:
        task.signals.failed.connect(failed)
    if finished is not None:
        task.signals.finished.connect(finished)
    QThreadPool.globalInstance().start(task)
    return task
