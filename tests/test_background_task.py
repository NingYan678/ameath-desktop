import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from digital_pet.background_task import start_task


def test_fast_background_task_can_attach_handlers_before_it_runs():
    app = QApplication.instance() or QApplication([])
    values = []
    finished = []
    _ = start_task(lambda: "done", succeeded=values.append, finished=lambda: finished.append(True))

    QThreadPool.globalInstance().waitForDone(1_000)
    app.processEvents()

    assert values == ["done"]
    assert finished == [True]
