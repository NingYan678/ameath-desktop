"""Windows foreground/full-screen observation without inspecting user content."""

from __future__ import annotations

import ctypes


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _Rect), ("rcWork", _Rect), ("dwFlags", ctypes.c_ulong)]


WS_MAXIMIZE = 0x01000000


def is_true_fullscreen(window: _Rect, monitor: _Rect, *, maximized: bool, tolerance: int = 4) -> bool:
    """Keep ordinary maximized work windows out of the game's protected state."""
    if maximized:
        return False
    return (
        abs(window.left - monitor.left) <= tolerance
        and abs(window.top - monitor.top) <= tolerance
        and abs(window.right - monitor.right) <= tolerance
        and abs(window.bottom - monitor.bottom) <= tolerance
    )


class ActivityMonitor:
    def fullscreen_foreground(self) -> bool:
        if __import__("os").name != "nt":
            return False
        try:
            user32 = ctypes.windll.user32
            handle = user32.GetForegroundWindow()
            if not handle:
                return False
            rect = _Rect()
            if not user32.GetWindowRect(handle, ctypes.byref(rect)):
                return False
            monitor = user32.MonitorFromWindow(handle, 2)
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return False
            style = user32.GetWindowLongW(handle, -16)
            return is_true_fullscreen(rect, info.rcMonitor, maximized=bool(style & WS_MAXIMIZE))
        except (AttributeError, OSError):
            return False
