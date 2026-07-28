import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from digital_pet.existing_hermes import HermesInstallation
from digital_pet.runtime_choice_dialog import RuntimeChoiceDialog


def test_runtime_choice_returns_qdialog_accepted_code():
    app = QApplication.instance() or QApplication([])
    root = Path(r"D:\hermes")
    installation = HermesInstallation(root, root / "python.exe", root / "hermes_cli.py", root / "hermes-agent", "fingerprint", False)
    dialog = RuntimeChoiceDialog(installation)

    dialog._choose("shared")

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.choice == "shared"


def test_runtime_choice_has_an_explicit_later_option():
    app = QApplication.instance() or QApplication([])
    root = Path(r"D:\hermes")
    installation = HermesInstallation(root, root / "python.exe", root / "hermes_cli.py", root / "hermes-agent", "fingerprint", False)
    dialog = RuntimeChoiceDialog(installation)

    later = next(button for button in dialog.findChildren(QPushButton) if button.text() == "暂不设置")
    later.click()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.choice is None
