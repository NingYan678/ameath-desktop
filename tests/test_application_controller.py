import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from digital_pet.application_controller import ApplicationController


class FakeSignal:
    def connect(self, callback):
        self.callback = callback


class FakeServer:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.newConnection = FakeSignal()

    def listen(self, name):
        return self.outcomes.pop(0)


class FakeSocket:
    def __init__(self, error):
        self._error = error

    def connectToServer(self, name, mode):
        pass

    def waitForConnected(self, timeout):
        return False

    def error(self):
        return self._error


class FakeMutex:
    def __init__(self, acquired):
        self.acquired = acquired
        self.released = False

    def acquire(self):
        return self.acquired

    def release(self):
        self.released = True


def install_socket_fakes(monkeypatch, socket, removed):
    class SocketFactory:
        ServerNotFoundError = QLocalSocket.ServerNotFoundError
        ConnectionRefusedError = QLocalSocket.ConnectionRefusedError

        def __new__(cls):
            return socket

    class ServerClass:
        @staticmethod
        def removeServer(name):
            removed.append(name)

    monkeypatch.setattr("digital_pet.application_controller.QLocalSocket", SocketFactory)
    monkeypatch.setattr("digital_pet.application_controller.QLocalServer", ServerClass)


def test_second_instance_never_removes_or_reuses_the_primary_endpoint(monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = ApplicationController(app)
    controller._mutex = FakeMutex(False)
    controller._server = FakeServer([False])
    removed = []
    install_socket_fakes(monkeypatch, FakeSocket(QLocalSocket.SocketTimeoutError), removed)

    assert not controller.acquire_single_instance()
    assert removed == []


def test_mutex_owner_cleans_a_stale_endpoint_before_listening(monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = ApplicationController(app)
    controller._mutex = FakeMutex(True)
    controller._server = FakeServer([True])
    removed = []
    install_socket_fakes(monkeypatch, FakeSocket(QLocalSocket.ServerNotFoundError), removed)

    assert controller.acquire_single_instance()
    assert removed == [controller.server_name]
