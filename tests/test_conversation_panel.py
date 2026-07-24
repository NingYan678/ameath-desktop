import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from digital_pet.conversation_panel import ConversationPanel
from digital_pet.preferences import DesktopPreferences


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_continuous_panel_keeps_only_the_latest_ten_messages(app):
    panel = ConversationPanel()

    for index in range(12):
        panel.add_user_message(f"message {index}")

    assert panel.is_expanded
    assert [message.content for message in panel.messages] == [f"message {index}" for index in range(2, 12)]


def test_streaming_draft_is_replaced_by_one_final_assistant_message(app):
    panel = ConversationPanel()

    panel.add_user_message("hello")
    panel.update_assistant_draft("first")
    panel.update_assistant_draft("second")
    panel.finalize_assistant("final")

    assert [(message.role, message.content, message.draft) for message in panel.messages] == [
        ("user", "hello", False),
        ("assistant", "final", False),
    ]
    assert not panel.is_streaming


def test_auto_collapse_waits_for_unsent_text_or_native_action(app):
    panel = ConversationPanel()

    panel.expand()
    panel.composer.setPlainText("draft")
    assert not panel.can_auto_collapse()
    panel.clear_composer()
    assert panel.collapse()

    panel.expand()
    panel.show_action("approve?", "批准", "拒绝")
    assert not panel.can_auto_collapse()
    panel.clear_action()
    assert panel.collapse()


def test_panel_opacity_updates_the_surface_and_message_layers(app):
    panel = ConversationPanel()

    panel.apply_preferences(DesktopPreferences(panel_opacity=20))
    transparent_style = panel.styleSheet()
    panel.apply_preferences(DesktopPreferences(panel_opacity=100))
    opaque_style = panel.styleSheet()

    assert "background: rgba(66, 51, 87, 77)" in transparent_style
    assert "background: rgba(66, 51, 87, 255)" in opaque_style
    assert "QFrame#expandedFrame { background: rgba(58, 44, 79, 67)" in transparent_style
    assert "QFrame#expandedFrame { background: rgba(58, 44, 79, 255)" in opaque_style
    assert "QFrame#messageIncoming { background: rgba(52, 43, 78, 134)" in transparent_style
    assert "QFrame#messageIncoming { background: rgba(52, 43, 78, 200)" in opaque_style
    assert "QFrame#messageOutgoing { background: rgba(126, 112, 194, 166)" in transparent_style
    assert "QFrame#messageOutgoing { background: rgba(126, 112, 194, 228)" in opaque_style
