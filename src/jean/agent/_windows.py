"""Windows application transition capture via Win32 API polling.

Uses ctypes to call GetForegroundWindow() + GetWindowThreadProcessId()
without requiring pywin32 — the standard library ctypes.windll is sufficient.

Polls every POLL_INTERVAL_S seconds for foreground window changes and yields
an APP_BLUR / APP_FOCUS pair on each transition.

Privacy: captures only the process executable name (basename without .exe),
never the window title or any document content.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import os
from collections.abc import AsyncGenerator

from jean.models import EventType

# Type alias mirrors _macos.py / _linux.py convention
_AppFocusEvent = tuple[str, EventType]

POLL_INTERVAL_S = 0.5

# Win32 process-access flags
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010


def _active_app_name() -> str | None:
    """Return process basename (without .exe) of the foreground window.

    Uses ctypes only — no pywin32 dependency required.
    Returns None on any error (window handle 0, access denied, etc.).
    """
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        psapi = ctypes.windll.psapi  # type: ignore[attr-defined]

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None

        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, False, pid.value
        )
        if not handle:
            return None

        try:
            buf = ctypes.create_unicode_buffer(260)
            psapi.GetModuleFileNameExW(handle, None, buf, 260)
            exe_path = buf.value
            if not exe_path:
                return None
            return os.path.splitext(os.path.basename(exe_path))[0] or None
        finally:
            kernel32.CloseHandle(handle)

    except (OSError, AttributeError):
        return None


async def observe_app_transitions() -> AsyncGenerator[_AppFocusEvent, None]:
    """Async generator that yields (app_name, EventType) on each focus change.

    On each transition the previous app emits APP_BLUR, the new app emits
    APP_FOCUS.

    Raises OSError wrapping the original error if ctypes.windll is not
    available (i.e. non-Windows environment) so AppTransitionCapture can
    catch and log it gracefully.
    """
    # Validate we are actually on Windows before entering the loop
    try:
        _ = ctypes.windll.user32  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise OSError("ctypes.windll is not available on this platform") from exc

    previous: str | None = None

    while True:
        await asyncio.sleep(POLL_INTERVAL_S)
        current = _active_app_name()
        if current and current != previous:
            if previous:
                yield previous, EventType.APP_BLUR
            yield current, EventType.APP_FOCUS
            previous = current
