"""Thin PySide client for the Hermes-native Ameath desktop platform."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtWebSockets import QWebSocket

from .config import Settings


class HermesDesktopClient(QObject):
    """Connects to the running Hermes Gateway; it never starts an agent."""

    connected = Signal()
    disconnected = Signal(str)
    event_received = Signal(dict)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runtime_path: Path = settings.desktop_runtime_path
        self._socket = QWebSocket()
        self._endpoint = ""
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_message)
        self._socket.errorOccurred.connect(self._on_error)
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(1_500)
        self._retry_timer.timeout.connect(self._connect_if_possible)

    def start(self) -> None:
        self._retry_timer.start()
        self._connect_if_possible()

    def close(self) -> None:
        self._retry_timer.stop()
        self._socket.close()

    def send_user_message(self, text: str) -> bool:
        return self._send({"type": "user_message", "text": text})

    def resolve_approval(self, session_key: str, choice: str) -> bool:
        return self._send({"type": "approval", "session_key": session_key, "choice": choice})

    def resolve_clarify(self, clarify_id: str, response: str) -> bool:
        return self._send({"type": "clarify", "clarify_id": clarify_id, "response": response})

    def resolve_slash_confirm(self, confirm_id: str, choice: str) -> bool:
        return self._send({"type": "slash_confirm", "confirm_id": confirm_id, "choice": choice})

    def _send(self, payload: dict[str, Any]) -> bool:
        if not self._socket.isValid():
            self.disconnected.emit("未连接到 Hermes Gateway。")
            return False
        self._socket.sendTextMessage(json.dumps(payload, ensure_ascii=False))
        return True

    def _connect_if_possible(self) -> None:
        if self._socket.isValid():
            return
        runtime = self._read_runtime()
        if runtime is None:
            return
        port, token = runtime
        query = QUrlQuery()
        query.addQueryItem("token", token)
        url = QUrl(f"ws://127.0.0.1:{port}/ameath-desktop")
        url.setQuery(query)
        endpoint = url.toString()
        if endpoint != self._endpoint:
            self._endpoint = endpoint
            self._socket.open(url)

    def _read_runtime(self) -> tuple[int, str] | None:
        try:
            payload = json.loads(self._runtime_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("state") != "ready":
            return None
        port, token = payload.get("port"), payload.get("token")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            return None
        if not isinstance(token, str) or len(token) < 24:
            return None
        return port, token

    def _on_connected(self) -> None:
        self.connected.emit()

    def _on_disconnected(self) -> None:
        self.disconnected.emit("Hermes Gateway 暂未连接，正在等待它恢复。")

    def _on_error(self, _error: object) -> None:
        if not self._socket.isValid():
            self.disconnected.emit("正在连接 Hermes Gateway…")

    def _on_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except ValueError:
            return
        if isinstance(payload, dict) and isinstance(payload.get("type"), str):
            self.event_received.emit(payload)
