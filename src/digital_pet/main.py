from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import sys

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .ameath_runtime import AmeathRuntimeService
from .application_controller import ApplicationController
from .config import application_root, default_data_root, is_packaged, load_settings
from .diagnostics import DiagnosticsService
from .legacy_hermes import BackendSelectionStore, ExistingHermesRuntimeService, ProbeStatus, discover_existing_hermes, probe_hermes_home
from .maintenance import reset_user_data
from .onboarding import OnboardingDialog
from .pet_window import PetWindow
from .runtime_choice_dialog import RuntimeChoiceDialog
from .version import APP_VERSION


def _configure_runtime_logging(data_root) -> None:  # type: ignore[no-untyped-def]
    logger = logging.getLogger("digital_pet.runtime")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return
    try:
        log_dir = data_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir / "runtime.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())


def _select_runtime(settings):  # type: ignore[no-untyped-def]
    store = BackendSelectionStore(settings.data_root)
    plugin_source = (settings.resources_root if is_packaged() else settings.install_root) / "hermes_platform" / "ameath_desktop"
    saved = store.load()
    if saved is not None:
        mode, home, fingerprint = saved
        if mode == "isolated":
            return AmeathRuntimeService(settings), store
        probe = probe_hermes_home(home, plugin_source)
        installation = probe.installation
        if installation is not None:
            if fingerprint != installation.fingerprint:
                answer = QMessageBox.question(None, "Hermes 配置已更新", "检测到本机 Hermes 配置已变化。是否重新验证后继续使用？", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
                if answer == QMessageBox.Cancel:
                    return None, store
                if answer == QMessageBox.No:
                    store.clear()
                    return _select_runtime(settings)
            store.save("shared", installation)
            return ExistingHermesRuntimeService(settings, installation), store
        store.clear()
        QMessageBox.warning(None, "本机 Hermes 不可用", f"之前选择的 Hermes 无法接入：{probe.message}")

    probe = discover_existing_hermes(settings)
    if probe.status is not ProbeStatus.AVAILABLE or probe.installation is None:
        if probe.status is not ProbeStatus.MISSING:
            QMessageBox.warning(None, "无法接入本机 Hermes", probe.message + "\n\n爱弥斯将改用独立配置。")
        return AmeathRuntimeService(settings), store
    installation = probe.installation
    dialog = RuntimeChoiceDialog(installation)
    if dialog.exec() != QDialog.DialogCode.Accepted or dialog.choice is None:
        return None, store
    store.save(dialog.choice, installation)
    if dialog.choice == "shared":
        return ExistingHermesRuntimeService(settings, installation), store
    return AmeathRuntimeService(settings), store


def _prepare_shared_runtime(runtime: ExistingHermesRuntimeService) -> bool:
    try:
        result = runtime.prepare()
    except (OSError, RuntimeError) as exc:
        QMessageBox.critical(None, "Cannot connect local Hermes", str(exc))
        return False
    # Identity verification runs in RuntimeSupervisor's background worker.
    # A shared Hermes is never started, restarted, or terminated during app boot.
    return True


def run() -> int:
    if "--reset-data" in sys.argv:
        return 0 if reset_user_data(default_data_root(), application_root()) else 3
    app = QApplication(sys.argv)
    app.setApplicationName("Ameath Desktop Pet")
    controller = ApplicationController(app)
    if not controller.acquire_single_instance():
        return 0
    settings = load_settings()
    _configure_runtime_logging(settings.data_root)
    diagnostics = DiagnosticsService(settings.data_root, version=APP_VERSION)
    diagnostics.install_exception_hook()
    runtime, selection_store = _select_runtime(settings)
    if runtime is None:
        return 0
    if isinstance(runtime, ExistingHermesRuntimeService):
        if not _prepare_shared_runtime(runtime):
            return 0
        window_settings = runtime.settings
    else:
        runtime.prepare()
        if not runtime.configured:
            OnboardingDialog(runtime).exec()
        elif runtime.runtime_available:
            runtime.start_gateway()
        window_settings = settings

    def reconfigure_backend() -> None:
        answer = QMessageBox.question(
            window,
            "切换 Hermes 后端",
            "将清除当前后端选择并退出爱弥斯。重新启动后可选择本机 Hermes、独立爱弥斯或暂不设置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        selection_store.clear()
        QMessageBox.information(window, "已清除 Hermes 选择", "请重新启动爱弥斯，以检测或选择 Hermes 后端。")
        app.quit()

    window = PetWindow(
        window_settings,
        runtime,
        shared_hermes=isinstance(runtime, ExistingHermesRuntimeService),
        backend_reconfigure=reconfigure_backend,
    )
    def export_diagnostics() -> str:
        from datetime import datetime
        path = settings.data_root / "diagnostics" / f"ameath-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.zip"
        try:
            diagnostics.export_bundle(path)
        except OSError as exc:
            QMessageBox.warning(window, "无法导出诊断包", str(exc))
            return ""
        QMessageBox.information(window, "诊断包已导出", f"已创建脱敏诊断包：\n{path}")
        return str(path)

    controller.attach(window, diagnostics=export_diagnostics)
    window.show()
    return app.exec()
