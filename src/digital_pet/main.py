from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication

from .ameath_runtime import AmeathRuntimeService
from .config import load_settings
from .onboarding import OnboardingDialog
from .pet_window import PetWindow


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ameath Desktop Pet")
    settings = load_settings()
    runtime = AmeathRuntimeService(settings)
    runtime.prepare()
    if not runtime.configured:
        OnboardingDialog(runtime).exec()
    elif runtime.runtime_available:
        runtime.start_gateway()
    window = PetWindow(settings, runtime)
    window.show()
    return app.exec()
