"""Linux application transition capture via xdotool polling.

Requires xdotool to be installed:
    sudo apt install xdotool   # Debian/Ubuntu
    sudo dnf install xdotool   # Fedora/RHEL

Polls every POLL_INTERVAL_S seconds for active window changes and yields
an APP_BLUR / APP_FOCUS pair on each transition.

Privacy: captures only the process name via /proc/{pid}/comm — never the
window title, document name, or any text content.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path

from jean.models import EventType

# Type alias mirrors _macos.py convention
_AppFocusEvent = tuple[str, EventType]

# Polling cadence — 500 ms is imperceptible to users while remaining
# lightweight (< 0.1 % CPU on a modern system).
POLL_INTERVAL_S = 0.5


def _active_app_name() -> str | None:
    """Return process name of the currently focused window, or None on error.

    Uses xdotool to resolve active-window → PID, then reads the comm file
    from /proc to obtain the executable name without a full path.
    """
    try:
        wid = subprocess.check_output(
            ["xdotool", "getactivewindow"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        if not wid:
            return None

        pid = subprocess.check_output(
            ["xdotool", "getwindowpid", wid],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        if not pid:
            return None

        comm = Path(f"/proc/{pid}/comm")
        if comm.exists():
            return comm.read_text().strip() or None
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return None


async def observe_app_transitions() -> AsyncGenerator[_AppFocusEvent, None]:
    """Async generator that yields (app_name, EventType) on each focus change.

    On each transition the previous app emits APP_BLUR, the new app emits
    APP_FOCUS.  The first focus is APP_FOCUS-only (no preceding blur).

    Raises ImportError if xdotool is not installed so that the caller
    (AppTransitionCapture) can catch it and log a user-friendly warning.
    """
    try:
        subprocess.check_output(
            ["xdotool", "--version"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except FileNotFoundError as exc:
        raise ImportError(
            "xdotool is required for Linux app-transition capture.\n"
            "Install with:  sudo apt install xdotool   # Debian/Ubuntu\n"
            "               sudo dnf install xdotool   # Fedora"
        ) from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass  # xdotool exists but version check returned non-zero — still usable

    previous: str | None = None

    while True:
        await asyncio.sleep(POLL_INTERVAL_S)
        current = _active_app_name()
        if current and current != previous:
            if previous:
                yield previous, EventType.APP_BLUR
            yield current, EventType.APP_FOCUS
            previous = current
