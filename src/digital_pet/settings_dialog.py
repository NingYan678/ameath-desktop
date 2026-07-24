"""Minimal settings center for the desktop surface and Hermes global options."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .hermes_settings import MANAGED_TOOLSETS, HermesSettingsService, HermesSettingsSnapshot
from .preferences import DesktopPreferences, StartupManager, UISettingsStore


class SliderSetting(QWidget):
    value_changed = Signal(int)

    def __init__(self, title: str, minimum: int, maximum: int, value: int, suffix: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        label_row = QHBoxLayout()
        self.title = QLabel(title, self)
        self.value_label = QLabel(self)
        self.value_label.setObjectName("settingValue")
        label_row.addWidget(self.title)
        label_row.addStretch(1)
        label_row.addWidget(self.value_label)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self._suffix = suffix
        self.slider.valueChanged.connect(self._changed)
        layout.addLayout(label_row)
        layout.addWidget(self.slider)
        self._changed(value)

    @property
    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.setValue(value)

    def _changed(self, value: int) -> None:
        self.value_label.setText(f"{value}{self._suffix}")
        self.value_changed.emit(value)


class SettingsDialog(QDialog):
    """Staged settings dialog: UI previews immediately, Hermes changes apply once."""

    def __init__(
        self,
        preferences: DesktopPreferences,
        store: UISettingsStore,
        startup: StartupManager,
        hermes: HermesSettingsService,
        preview: Callable[[DesktopPreferences], None],
        parent: QWidget | None = None,
        onboard: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial = preferences
        self._store = store
        self._startup = startup
        self._hermes = hermes
        self._preview = preview
        self._onboard = onboard
        self._snapshot = self._read_hermes()
        self.setWindowTitle("爱弥斯设置")
        self.setModal(True)
        self.setMinimumSize(570, 560)
        self.setStyleSheet(
            "QDialog { background: #252039; color: #fff9fd; }"
            "QLabel { color: #fff9fd; } QLabel#muted, QLabel#settingValue { color: #d9cce8; }"
            "QTabWidget::pane { border: 1px solid #564967; border-radius: 12px; top: -1px; }"
            "QTabBar::tab { background: transparent; color: #cfc1df; padding: 8px 16px; margin-right: 2px; }"
            "QTabBar::tab:selected { color: #fff9fd; border-bottom: 2px solid #9ee9f5; }"
            "QFrame#groupCard { background: #302942; border: 1px solid #514661; border-radius: 12px; }"
            "QSlider::groove:horizontal { height: 4px; background: #564967; border-radius: 2px; }"
            "QSlider::sub-page:horizontal { background: #e9a8d0; border-radius: 2px; }"
            "QSlider::handle:horizontal { background: #fff1f8; width: 14px; margin: -5px 0; border-radius: 7px; }"
            "QLineEdit, QComboBox, QListWidget { background: #211c31; color: #fff9fd; border: 1px solid #584b68; border-radius: 8px; padding: 6px; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
            "QPushButton { background: #433852; color: #fff9fd; border: 1px solid #675672; border-radius: 8px; padding: 7px 12px; }"
            "QPushButton:hover { background: #574661; } QPushButton#applyButton { background: #ffe1ef; color: #533b5a; border: none; font-weight: 600; }"
            "QPushButton#applyButton:hover { background: #fff0f7; }"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("设置", self)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        subtitle = QLabel("外观调整会即时预览；桌宠保存与 Hermes 全局应用是两项独立操作。", self)
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        tabs = QTabWidget(self)
        tabs.addTab(self._appearance_tab(), "外观")
        tabs.addTab(self._desktop_tab(), "桌宠")
        tabs.addTab(self._hermes_tab(), "Hermes")
        layout.addWidget(tabs, 1)

        actions = QHBoxLayout()
        reset = QPushButton("恢复外观默认", self)
        reset.clicked.connect(self._reset_appearance)
        actions.addWidget(reset)
        actions.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        save_desktop = QPushButton("保存桌宠设置", self)
        save_desktop.clicked.connect(self._save_desktop)
        apply_button = QPushButton("应用 Hermes 并重启", self)
        apply_button.setObjectName("applyButton")
        apply_button.clicked.connect(self._apply_hermes)
        actions.addWidget(cancel)
        actions.addWidget(save_desktop)
        actions.addWidget(apply_button)
        layout.addLayout(actions)

    def _appearance_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 16, 14, 14)
        card = self._card("外观与布局", "调整时会立刻预览到桌宠窗口。")
        card_layout = card.layout()
        self.pet_size = SliderSetting("桌宠大小", 120, 360, self._initial.pet_size, " px", card)
        self.compact_width = SliderSetting("紧凑对话宽度", 300, 560, self._initial.compact_width, " px", card)
        self.expanded_width = SliderSetting("展开对话宽度", 380, 760, self._initial.expanded_width, " px", card)
        self.expanded_height = SliderSetting("展开对话高度", 280, 760, self._initial.expanded_height, " px", card)
        self.opacity = SliderSetting("背景不透明度（越低越透明）", 20, 100, self._initial.panel_opacity, "%", card)
        self.font_scale = SliderSetting("文字大小", 80, 150, self._initial.font_scale, "%", card)
        for control in (self.pet_size, self.compact_width, self.expanded_width, self.expanded_height, self.opacity, self.font_scale):
            control.value_changed.connect(self._preview_current)
            card_layout.addWidget(control)
        layout.addWidget(card)
        layout.addStretch(1)
        return tab

    def _desktop_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 16, 14, 14)
        card = self._card("桌宠行为", "这些选项仅影响本机爱弥斯桌宠。")
        card_layout = card.layout()
        self.animation_speed = SliderSetting("动画速度", 50, 200, self._initial.animation_speed, "%", card)
        self.auto_collapse = SliderSetting("自动收缩等待", 5, 180, self._initial.auto_collapse_seconds, " 秒", card)
        self.always_top = QCheckBox("始终置顶", card)
        self.always_top.setChecked(self._initial.always_on_top)
        self.launch_login = QCheckBox("登录 Windows 时启动桌宠", card)
        self.launch_login.setChecked(self._startup.is_enabled() or self._initial.launch_at_login)
        self.animation_speed.value_changed.connect(self._preview_current)
        self.auto_collapse.value_changed.connect(self._preview_current)
        self.always_top.toggled.connect(self._preview_current)
        card_layout.addWidget(self.animation_speed)
        card_layout.addWidget(self.auto_collapse)
        card_layout.addWidget(self.always_top)
        card_layout.addWidget(self.launch_login)
        layout.addWidget(card)
        layout.addStretch(1)
        return tab

    def _hermes_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 16, 14, 14)
        status = "运行中" if self._snapshot.gateway_running else "未检测到运行中的 Gateway"
        card = self._card("全局 Hermes", f"Gateway：{status}。凭据继续由 Hermes 自身管理，不会在此显示。")
        card_layout = card.layout()
        form = QFormLayout()
        self.model = QLineEdit(self._snapshot.model, card)
        self.model.setPlaceholderText("默认模型")
        self.provider = QLineEdit(self._snapshot.provider, card)
        self.provider.setPlaceholderText("Provider，例如 auto")
        self.personality = QComboBox(card)
        names = ["none", *self._snapshot.personalities]
        self.personality.addItems(names)
        current = self.personality.findText(self._snapshot.active_personality)
        self.personality.setCurrentIndex(max(0, current))
        form.addRow("默认模型", self.model)
        form.addRow("Provider", self.provider)
        form.addRow("人格", self.personality)
        card_layout.addLayout(form)
        card_layout.addWidget(QLabel("共享工具集", card))
        tools_hint = QLabel("改变工具可用性，不会跳过 Hermes 的逐次授权确认。", card)
        tools_hint.setObjectName("muted")
        tools_hint.setWordWrap(True)
        card_layout.addWidget(tools_hint)
        self.tools = QListWidget(card)
        self.tools.setSelectionMode(QListWidget.NoSelection)
        enabled_tools = set(self._snapshot.enabled_tools)
        for tool in MANAGED_TOOLSETS:
            item = QListWidgetItem(tool, self.tools)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if tool in enabled_tools else Qt.Unchecked)
        self.tools.setMaximumHeight(150)
        card_layout.addWidget(self.tools)
        if self._onboard is not None:
            setup = QPushButton("重新配置模型服务", card)
            setup.clicked.connect(self._onboard)
            card_layout.addWidget(setup)
        layout.addWidget(card)
        layout.addStretch(1)
        return tab

    def _card(self, title: str, description: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName("groupCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(9)
        heading = QLabel(title, card)
        heading.setStyleSheet("font-size: 14px; font-weight: 700;")
        note = QLabel(description, card)
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(note)
        return card

    def _preferences_from_controls(self) -> DesktopPreferences:
        return DesktopPreferences(
            pet_size=self.pet_size.value,
            compact_width=self.compact_width.value,
            expanded_width=max(self.expanded_width.value, self.compact_width.value),
            expanded_height=self.expanded_height.value,
            panel_opacity=self.opacity.value,
            font_scale=self.font_scale.value,
            animation_speed=self.animation_speed.value,
            auto_collapse_seconds=self.auto_collapse.value,
            always_on_top=self.always_top.isChecked(),
            launch_at_login=self.launch_login.isChecked(),
        )

    def _preview_current(self, *_: object) -> None:
        self._preview(self._preferences_from_controls())

    def _reset_appearance(self) -> None:
        defaults = DesktopPreferences()
        self.pet_size.set_value(defaults.pet_size)
        self.compact_width.set_value(defaults.compact_width)
        self.expanded_width.set_value(defaults.expanded_width)
        self.expanded_height.set_value(defaults.expanded_height)
        self.opacity.set_value(defaults.panel_opacity)
        self.font_scale.set_value(defaults.font_scale)

    def _selected_tools(self) -> list[str]:
        return [
            self.tools.item(index).text()
            for index in range(self.tools.count())
            if self.tools.item(index).checkState() == Qt.Checked
        ]

    def _persist_desktop(self) -> DesktopPreferences:
        preferences = self._preferences_from_controls()
        self._store.save(preferences)
        self._startup.set_enabled(preferences.launch_at_login)
        self._preview(preferences)
        self._initial = preferences
        return preferences

    def _save_desktop(self) -> None:
        try:
            self._persist_desktop()
        except OSError as exc:
            QMessageBox.warning(self, "桌宠设置未保存", str(exc))
            return
        QMessageBox.information(self, "桌宠设置已保存", "外观和桌宠行为已立即生效，无需重启 Hermes。")

    def _apply_hermes(self) -> None:
        try:
            preferences = self._persist_desktop()
            self._hermes.apply_and_restart(
                model=self.model.text(),
                provider=self.provider.text(),
                personality=self.personality.currentText(),
                tools=self._selected_tools(),
            )
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Hermes 设置未完全应用", f"桌宠设置已保存。\n\n{exc}")
            return
        self._preview(preferences)
        QMessageBox.information(self, "Hermes 设置已应用", "桌宠设置已保存，Hermes Gateway 正在重启并会自动重连。")
        self.accept()

    def reject(self) -> None:
        self._preview(self._initial)
        super().reject()

    def _read_hermes(self) -> HermesSettingsSnapshot:
        try:
            return self._hermes.read()
        except RuntimeError:
            return HermesSettingsSnapshot("", "auto", "none", (), (), False)
