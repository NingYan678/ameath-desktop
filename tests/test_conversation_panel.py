import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTextBrowser

from digital_pet.conversation_panel import ConversationPanel, IconButton
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


def test_assistant_markdown_uses_rich_text_but_user_text_stays_plain(app):
    panel = ConversationPanel()
    panel.add_user_message("<b>user</b>")
    panel.finalize_assistant("# 标题\n\n[链接](https://example.com)")

    browsers = panel.findChildren(QTextBrowser)
    assert len(browsers) == 1
    assert "标题" in browsers[0].toPlainText()
    assert "https://example.com" in browsers[0].toHtml()
    assert panel.messages[0].content == "<b>user</b>"


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


def test_common_chat_actions_use_accessible_icon_buttons(app):
    panel = ConversationPanel()

    for button, label in (
        (panel.expand_button, "展开对话"),
        (panel.collapse_button, "收起对话"),
        (panel.settings_button, "设置"),
        (panel.send_button, "发送消息"),
    ):
        assert isinstance(button, IconButton)
        assert button.text() == ""
        assert button.toolTip() == label
        assert button.accessibleName() == label
        assert button.focusPolicy().name == "StrongFocus"

    assert panel.confirm_button.text()
    assert panel.cancel_button.text()
