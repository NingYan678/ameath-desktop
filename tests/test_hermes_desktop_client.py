import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from digital_pet.config import Settings
from digital_pet.hermes_desktop_client import HermesDesktopClient, format_proactive_reply


class FakeSocket:
    def __init__(self):
        self.opened = []

    def isValid(self):
        return False

    def open(self, url):
        self.opened.append(url)


def test_disconnect_clears_endpoint_so_the_same_gateway_can_reconnect(tmp_path):
    _ = QApplication.instance() or QApplication([])
    settings = Settings(tmp_path / "assets", tmp_path / "data", tmp_path / "python.exe", tmp_path / "main.py")
    client = HermesDesktopClient(settings)
    socket = FakeSocket()
    client._socket = socket
    client._endpoint = "ws://127.0.0.1:1234/ameath-desktop?token=old"
    client._read_runtime = lambda: (1234, "x" * 24)

    client._on_disconnected()
    client._connect_if_possible()

    assert client._endpoint
    assert len(socket.opened) == 1


def test_proactive_reply_is_embedded_in_text_for_older_plugins():
    context = {"kind": "proactive_reply", "event_id": "morning-plan", "prompt": "今天想先完成什么？"}

    formatted = format_proactive_reply("我想先整理桌面。", context)

    assert "【爱弥斯主动提问】" in formatted
    assert "爱弥斯：今天想先完成什么？" in formatted
    assert "用户回答：我想先整理桌面。" in formatted
    assert formatted.count("爱弥斯主动提问") == 1


def test_proactive_reply_is_not_wrapped_without_valid_context():
    assert format_proactive_reply("普通消息", None) == "普通消息"
    assert format_proactive_reply("普通消息", {"kind": "proactive_reply", "prompt": "问题"}) == "普通消息"
