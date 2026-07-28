"""First-run model setup for people who should never need a terminal."""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .ameath_runtime import AmeathRuntimeService, ModelProfile, PROVIDER_DEFAULTS
from .background_task import FunctionTask, start_task


class OnboardingDialog(QDialog):
    """Collects only what is needed to start the private Ameath Hermes core."""

    _labels = {
        "deepseek": "DeepSeek",
        "openai": "OpenAI",
        "compatible": "OpenAI 兼容接口",
        "ollama": "Ollama（本机）",
    }

    def __init__(self, runtime: AmeathRuntimeService, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.runtime = runtime
        self._task: FunctionTask | None = None
        self.setWindowTitle("欢迎使用爱弥斯")
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setStyleSheet(
            "QDialog { background: #252039; color: #fff9fd; } QLabel { color: #fff9fd; }"
            "QLineEdit, QComboBox { background: #211c31; color: #fff9fd; border: 1px solid #584b68; border-radius: 8px; padding: 7px; }"
            "QPushButton { background: #433852; color: #fff9fd; border: 1px solid #675672; border-radius: 8px; padding: 7px 12px; }"
            "QPushButton#primary { background: #ffe1ef; color: #533b5a; border: none; font-weight: 600; }"
        )
        self._build_ui()
        self._select_provider()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        heading = QLabel("让爱弥斯准备就绪", self)
        heading.setStyleSheet("font-size: 22px; font-weight: 700;")
        detail = QLabel("选择你已有的 AI 服务。密钥仅加密保存在这台电脑的当前 Windows 账户中。", self)
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #d9cce8;")
        layout.addWidget(heading)
        layout.addWidget(detail)

        form = QFormLayout()
        form.setSpacing(10)
        self.provider = QComboBox(self)
        for key, label in self._labels.items():
            self.provider.addItem(label, key)
        self.model = QLineEdit(self)
        self.base_url = QLineEdit(self)
        self.api_key = QLineEdit(self)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("仅用于连接模型服务")
        form.addRow("模型服务", self.provider)
        form.addRow("模型名称", self.model)
        form.addRow("服务地址", self.base_url)
        self.key_label = QLabel("API Key", self)
        form.addRow(self.key_label, self.api_key)
        layout.addLayout(form)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #d9cce8;")
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        self.test_button = QPushButton("测试连接", self)
        self.test_button.clicked.connect(self._test_connection)
        actions.addWidget(self.test_button)
        actions.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        buttons.rejected.connect(self.reject)
        self.finish_button = QPushButton("完成并启动", self)
        self.finish_button.setObjectName("primary")
        self.finish_button.clicked.connect(self._finish)
        actions.addWidget(buttons)
        actions.addWidget(self.finish_button)
        layout.addLayout(actions)
        self.provider.currentIndexChanged.connect(self._select_provider)

    def _select_provider(self) -> None:
        profile = PROVIDER_DEFAULTS[self.provider.currentData()]
        self.model.setText(profile.model)
        self.base_url.setText(profile.base_url)
        local = profile.provider == "ollama"
        self.api_key.setVisible(not local)
        self.key_label.setVisible(not local)
        self.api_key.setText("")
        self.status.setText("Ollama 需要先在这台电脑上运行。" if local else "")

    def profile(self) -> ModelProfile:
        return ModelProfile(
            provider=str(self.provider.currentData()),
            model=self.model.text().strip(),
            base_url=self.base_url.text().strip(),
            api_key=self.api_key.text().strip(),
        )

    @staticmethod
    def test_profile(profile: ModelProfile) -> tuple[bool, str]:
        if not profile.model or not profile.base_url:
            return False, "请先填写模型名称和服务地址。"
        if profile.needs_api_key and not profile.api_key:
            return False, "请先填写 API Key。"
        if profile.provider == "ollama":
            endpoint = profile.base_url.replace("/v1", "").rstrip("/") + "/api/tags"
            headers = {}
        else:
            endpoint = profile.base_url.rstrip("/") + "/models"
            headers = {"Authorization": f"Bearer {profile.api_key}"}
        try:
            request = Request(endpoint, headers=headers)
            with urlopen(request, timeout=8.0) as response:
                status_code = response.status
        except HTTPError as exc:
            status_code = exc.code
        except (OSError, URLError, ValueError):
            return False, "无法连接到该服务，请检查网络、地址和本地服务状态。"
        if 200 <= status_code < 300:
            return True, "连接成功。"
        if status_code in {401, 403}:
            return False, "服务拒绝了凭据，请检查 API Key。"
        return False, f"服务返回了 {status_code}，请检查地址和模型服务状态。"

    def _test_connection(self) -> None:
        profile = self.profile()
        self._run_task(lambda: self.test_profile(profile), self._show_connection_result)

    def _finish(self) -> None:
        profile = self.profile()
        def finish() -> tuple[bool, str]:
            valid, message = self.test_profile(profile)
            if not valid:
                return False, message
            self.runtime.save_profile(profile)
            if not self.runtime.start_gateway():
                return False, "爱弥斯内核尚未准备好，请重新安装或检查运行环境。"
            return True, "模型服务已保存，正在连接 Hermes。"
        self._run_task(finish, self._finish_result)

    def _run_task(self, operation, on_success) -> None:  # type: ignore[no-untyped-def]
        if self._task is not None:
            return
        self.test_button.setEnabled(False)
        self.finish_button.setEnabled(False)
        self.status.setText("正在处理，请稍候…")
        self.status.setStyleSheet("color: #d9cce8;")
        task = start_task(operation)
        self._task = task
        task.signals.succeeded.connect(on_success)
        task.signals.failed.connect(self._task_failed)
        task.signals.finished.connect(self._task_finished)

    def _show_connection_result(self, result: object) -> None:
        valid, message = result  # type: ignore[misc]
        self.status.setText(message)
        self.status.setStyleSheet("color: #a7eff7;" if valid else "color: #ffc0d8;")

    def _finish_result(self, result: object) -> None:
        valid, message = result  # type: ignore[misc]
        if valid:
            self.status.setText(message)
            self.accept()
        else:
            QMessageBox.warning(self, "暂时无法完成设置", message)

    def _task_failed(self, message: str) -> None:
        QMessageBox.critical(self, "启动失败", message)

    def _task_finished(self) -> None:
        self._task = None
        self.test_button.setEnabled(True)
        self.finish_button.setEnabled(True)
