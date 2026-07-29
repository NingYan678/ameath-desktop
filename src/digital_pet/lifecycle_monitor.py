"""Windows session, power and display lifecycle signals for a resident pet."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal


class LifecycleMonitor(QObject, QAbstractNativeEventFilter):
    suspended = Signal()
    resumed = Signal()
    session_locked = Signal()
    session_unlocked = Signal()
    display_changed = Signal()
    low_power_changed = Signal(bool)

    WM_POWERBROADCAST = 0x0218
    WM_DISPLAYCHANGE = 0x007E
    WM_WTSSESSION_CHANGE = 0x02B1
    PBT_APMSUSPEND = 0x0004
    PBT_APMRESUMEAUTOMATIC = 0x0012
    PBT_APMRESUMESUSPEND = 0x0007
    WTS_SESSION_LOCK = 0x0007
    WTS_SESSION_UNLOCK = 0x0008

    class _Msg(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt_x", wintypes.LONG), ("pt_y", wintypes.LONG)]

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._started = False
        self._hwnd: int | None = None
        self._battery_timer = QTimer(self)
        self._battery_timer.setInterval(60_000)
        self._battery_timer.timeout.connect(self._poll_power)
        self._low_power = False

    def start(self, hwnd: int | None = None) -> None:
        if self._started:
            return
        self._started = True
        self._hwnd = hwnd
        app = self.parent()
        if os.name == "nt" and app is not None and hasattr(app, "installNativeEventFilter"):
            app.installNativeEventFilter(self)
            if hwnd:
                try:
                    ctypes.windll.wtsapi32.WTSRegisterSessionNotification(hwnd, 0)
                except (AttributeError, OSError):
                    pass
        self._poll_power()
        self._battery_timer.start()

    def stop(self) -> None:
        if not self._started:
            return
        self._battery_timer.stop()
        app = self.parent()
        if os.name == "nt" and app is not None and hasattr(app, "removeNativeEventFilter"):
            app.removeNativeEventFilter(self)
            if self._hwnd:
                try:
                    ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(self._hwnd)
                except (AttributeError, OSError):
                    pass
        self._started = False

    def nativeEventFilter(self, event_type: bytes | str, message: int) -> tuple[bool, int]:  # noqa: N802
        if event_type not in {b"windows_generic_MSG", b"windows_dispatcher_MSG", "windows_generic_MSG", "windows_dispatcher_MSG"}:
            return False, 0
        try:
            msg = ctypes.cast(message, ctypes.POINTER(self._Msg)).contents
        except (ValueError, OSError):
            return False, 0
        if msg.message == self.WM_POWERBROADCAST:
            if msg.wParam == self.PBT_APMSUSPEND:
                self.suspended.emit()
            elif msg.wParam in {self.PBT_APMRESUMEAUTOMATIC, self.PBT_APMRESUMESUSPEND}:
                self.resumed.emit()
        elif msg.message == self.WM_DISPLAYCHANGE:
            self.display_changed.emit()
        elif msg.message == self.WM_WTSSESSION_CHANGE:
            if msg.wParam == self.WTS_SESSION_LOCK:
                self.session_locked.emit()
            elif msg.wParam == self.WTS_SESSION_UNLOCK:
                self.session_unlocked.emit()
        return False, 0

    def _poll_power(self) -> None:
        if os.name != "nt":
            return
        class _PowerStatus(ctypes.Structure):
            _fields_ = [("ac_line", wintypes.BYTE), ("battery_flag", wintypes.BYTE), ("battery_percent", wintypes.BYTE), ("reserved", wintypes.BYTE), ("battery_life", wintypes.DWORD), ("battery_full", wintypes.DWORD)]

        status = _PowerStatus()
        try:
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                return
        except (AttributeError, OSError):
            return
        low_power = status.ac_line == 0 and status.battery_percent != 255
        if low_power != self._low_power:
            self._low_power = low_power
            self.low_power_changed.emit(low_power)
