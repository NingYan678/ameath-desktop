"""The explicit first-run choice between local and isolated Hermes runtimes."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from .legacy_hermes import HermesInstallation


class RuntimeChoiceDialog(QDialog):
    def __init__(self, installation: HermesInstallation, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.choice: str | None = None
        self.setWindowTitle("检测到本机 Hermes")
        self.setModal(True)
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        heading = QLabel("检测到可用的本机 Hermes", self)
        heading.setStyleSheet("font-size: 20px; font-weight: 700;")
        detail = QLabel(
            "爱弥斯可以使用它已有的模型配置和凭据，不会复制 API Key。\n\n"
            f"位置：{installation.home}\n\n"
            "选择后会安装并启用爱弥斯桌面插件。未验证的运行中 Gateway 不会被桌宠自动终止。",
            self,
        )
        detail.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(detail)
        use_existing = QPushButton("使用本机 Hermes", self)
        use_existing.clicked.connect(lambda: self._choose("shared"))
        isolated = QPushButton("为爱弥斯单独配置", self)
        isolated.clicked.connect(lambda: self._choose("isolated"))
        later = QPushButton("暂不设置", self)
        later.clicked.connect(self.reject)
        layout.addWidget(use_existing)
        layout.addWidget(isolated)
        layout.addWidget(later)

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()
