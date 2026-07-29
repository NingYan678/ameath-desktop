"""Windows application shell: one instance, tray controls and safe shutdown."""

from __future__ import annotations

import ctypes
import hashlib
import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QIODevice
from PySide6.QtGui import QAction, QCursor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

if TYPE_CHECKING:
    from .pet_window import PetWindow


class SessionMutex:
    """Windows session-wide ownership guard; the socket only wakes the owner."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str) -> None:
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            return False
        if ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None and os.name == "nt":
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._handle)
        self._handle = None


class ApplicationController:
    """Owns process-lifetime concerns; windows only present UI state."""

    def __init__(self, app: QApplication) -> None:
        self.app = app
        identity = os.environ.get("USERNAME", "default").encode("utf-8", "ignore")
        self.server_name = "AmeathDesktopPet-" + hashlib.sha256(identity).hexdigest()[:16]
        self._mutex = SessionMutex("Local\\" + self.server_name)
        self._server = QLocalServer()
        self._window: PetWindow | None = None
        self._tray: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None
        self._pause_action: QAction | None = None
        self._proactive_action: QAction | None = None
        self._game_action: QAction | None = None
        self._peers: list[QLocalSocket] = []
        self._quitting = False
        self.app.aboutToQuit.connect(self._mutex.release)

    def acquire_single_instance(self, *, command: bytes = b"show") -> bool:
        """Returns False after sending a small local command to the existing instance."""
        if not self._mutex.acquire():
            self._wake_existing_instance(command)
            return False
        # Owning the mutex proves no live process can own this endpoint.
        QLocalServer.removeServer(self.server_name)
        if self._server.listen(self.server_name):
            self._server.newConnection.connect(self._on_new_connection)
            return True
        self._mutex.release()
        return False

    def _wake_existing_instance(self, command: bytes = b"show") -> None:
        """Best effort only: a second launch must never become a second pet."""
        for _ in range(3):
            socket = QLocalSocket()
            socket.connectToServer(self.server_name, QIODevice.WriteOnly)
            if socket.waitForConnected(500):
                socket.write(command)
                socket.waitForBytesWritten(300)
                socket.disconnectFromServer()
                return
            time.sleep(0.1)

    def attach(self, window: PetWindow, *, diagnostics: Callable[[], str] | None = None) -> None:
        self._window = window
        window.set_close_handler(self.request_close)
        window.context_menu_requested.connect(self.show_context_menu)
        window.proactive_changed.connect(self._on_proactive_changed)
        self._tray = QSystemTrayIcon(window.windowIcon(), self.app)
        self._menu = QMenu()
        self._menu.addAction("显示 / 隐藏", self.toggle_visibility)
        self._menu.addAction("打开聊天", self._open_chat)
        self._menu.addAction("让爱弥斯说句话", window.trigger_proactive_now)
        self._menu.addSeparator()
        self._pause_action = self._menu.addAction("暂停动画", window.toggle_pause)
        self._proactive_action = self._menu.addAction("主动互动：已开启", window.toggle_proactive)
        self._proactive_action.setCheckable(True)
        self._game_action = self._menu.addAction("进入游戏模式", window.toggle_game_mode)
        self._game_action.setCheckable(True)
        self._menu.addAction("重新连接 Hermes", window.reconnect_gateway)
        self._menu.addAction("设置", self._open_settings)
        if diagnostics is not None:
            self._menu.addAction("导出诊断包", diagnostics)
        self._menu.addSeparator()
        self._menu.addAction("退出爱弥斯", self.quit)
        self._menu.aboutToShow.connect(self._refresh_menu)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    def request_close(self) -> bool:
        """Called by the window close event. True means close was converted to hide."""
        if self._quitting:
            return False
        if self._window is not None and self._window.preferences.close_to_tray:
            assert self._window is not None
            self._window.hide()
            if self._tray is not None and self._tray.supportsMessages():
                self._tray.showMessage("爱弥斯", "已隐藏到系统托盘；可从托盘重新打开。")
            return True
        return False

    def toggle_visibility(self) -> None:
        if self._window is None:
            return
        if self._window.isVisible():
            self._window.hide()
        else:
            self.show_window()

    def show_window(self) -> None:
        if self._window is None:
            return
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def show_context_menu(self) -> None:
        if self._menu is not None:
            self._menu.exec(QCursor.pos())

    def quit(self) -> None:
        self._quitting = True
        if self._tray is not None:
            self._tray.hide()
        if self._window is not None:
            self._window.close()
        self.app.quit()

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._peers.append(socket)
            socket.readyRead.connect(lambda peer=socket: self._read_command(peer))
            socket.disconnected.connect(lambda peer=socket: self._release_peer(peer))
            if socket.bytesAvailable():
                self._read_command(socket)

    def _read_command(self, socket: QLocalSocket) -> None:
        command = bytes(socket.readAll()).strip()
        if command == b"show":
            self.show_window()
        elif command == b"proactive" and self._window is not None:
            self._window.trigger_proactive_now()

    def _release_peer(self, socket: QLocalSocket) -> None:
        if socket in self._peers:
            self._peers.remove(socket)
        socket.deleteLater()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick}:
            self.toggle_visibility()

    def _open_chat(self) -> None:
        self.show_window()
        if self._window is not None:
            self._window.open_chat()

    def _open_settings(self) -> None:
        self.show_window()
        if self._window is not None:
            self._window.open_settings()

    def _on_proactive_changed(self, enabled: bool) -> None:
        self._set_proactive_action(enabled)
        if self._tray is not None and self._tray.supportsMessages():
            message = "主动互动已开启。" if enabled else "主动互动已暂停。"
            self._tray.showMessage("爱弥斯", message)

    def _set_proactive_action(self, enabled: bool) -> None:
        if self._proactive_action is None:
            return
        self._proactive_action.setChecked(enabled)
        self._proactive_action.setText("主动互动：已开启" if enabled else "主动互动：已暂停")

    def _refresh_menu(self) -> None:
        if self._window is not None and self._pause_action is not None:
            self._pause_action.setText("继续动画" if self._window.animation_paused else "暂停动画")
        if self._window is not None and self._game_action is not None:
            self._game_action.setChecked(self._window.game_mode_active)
            self._game_action.setText("退出游戏模式" if self._window.game_mode_active else "进入游戏模式")
        if self._window is not None:
            self._set_proactive_action(self._window.preferences.proactive_enabled)
