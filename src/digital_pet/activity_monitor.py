"""Windows foreground/full-screen observation without inspecting user content."""

from __future__ import annotations

import ctypes


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _Rect), ("rcWork", _Rect), ("dwFlags", ctypes.c_ulong)]


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
            monitor_rect = info.rcMonitor
            window_area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
            screen_area = max(1, monitor_rect.right - monitor_rect.left) * max(1, monitor_rect.bottom - monitor_rect.top)
            return window_area / screen_area >= 0.95
        except (AttributeError, OSError):
            return False
