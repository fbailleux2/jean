"""Tests for jean/agent/_windows.py — Windows app-transition capture.

All tests mock ctypes so they run on any platform (macOS, Linux, CI).
Patching the entire ctypes module avoids the 'windll does not exist on
non-Windows' AttributeError — we replace ctypes with a MagicMock so
ctypes.windll becomes a MagicMock attribute automatically.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _active_app_name — unit tests
# ---------------------------------------------------------------------------

def test_active_app_name_returns_none_on_zero_hwnd():
    """GetForegroundWindow returns 0 → None (no window in focus)."""
    from jean.agent._windows import _active_app_name

    with patch("jean.agent._windows.ctypes") as mock_ctypes:
        mock_ctypes.windll.user32.GetForegroundWindow.return_value = 0
        result = _active_app_name()

    assert result is None


def test_active_app_name_returns_none_on_oserror():
    """OSError in Win32 call → None gracefully."""
    from jean.agent._windows import _active_app_name

    with patch("jean.agent._windows.ctypes") as mock_ctypes:
        mock_ctypes.windll.user32.GetForegroundWindow.side_effect = OSError("denied")
        result = _active_app_name()

    assert result is None


def test_active_app_name_returns_none_on_open_process_failure():
    """OpenProcess returns 0 (access denied) → None."""
    from jean.agent._windows import _active_app_name

    fake_dword = MagicMock()
    fake_dword.value = 42

    with patch("jean.agent._windows.ctypes") as mock_ctypes:
        mock_ctypes.windll.user32.GetForegroundWindow.return_value = 999
        mock_ctypes.wintypes.DWORD.return_value = fake_dword
        mock_ctypes.byref.return_value = fake_dword
        mock_ctypes.windll.kernel32.OpenProcess.return_value = 0  # failure
        result = _active_app_name()

    assert result is None


# ---------------------------------------------------------------------------
# observe_app_transitions — generator tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_observe_raises_oserror_when_windll_unavailable():
    """OSError raised when ctypes.windll is not available (non-Windows).

    On macOS/Linux, ctypes.windll doesn't exist — the generator should
    raise OSError immediately on first iteration.
    """
    from jean.agent._windows import observe_app_transitions

    # Simulate no windll by raising AttributeError on access
    mock_ctypes = MagicMock(spec=[])  # spec=[] means NO attributes

    with patch("jean.agent._windows.ctypes", mock_ctypes):
        gen = observe_app_transitions()
        with pytest.raises((OSError, AttributeError)):
            await gen.__anext__()


@pytest.mark.asyncio
async def test_observe_yields_app_focus_on_first_window():
    """First active window → APP_FOCUS event."""
    from jean.agent._windows import observe_app_transitions
    from jean.models import EventType

    with (
        patch("jean.agent._windows.ctypes") as mock_ctypes,
        patch("jean.agent._windows._active_app_name", return_value="notepad"),
        patch("jean.agent._windows.asyncio.sleep", return_value=None),
    ):
        gen = observe_app_transitions()
        app, etype = await gen.__anext__()

    assert app == "notepad"
    assert etype == EventType.APP_FOCUS


@pytest.mark.asyncio
async def test_observe_yields_blur_then_focus_on_app_change():
    """Window switch → (old, APP_BLUR) then (new, APP_FOCUS)."""
    from jean.agent._windows import observe_app_transitions
    from jean.models import EventType

    apps = iter(["notepad", "notepad", "chrome"])

    def _next():
        try:
            return next(apps)
        except StopIteration:
            return "chrome"

    with (
        patch("jean.agent._windows.ctypes"),
        patch("jean.agent._windows._active_app_name", side_effect=_next),
        patch("jean.agent._windows.asyncio.sleep", return_value=None),
    ):
        gen = observe_app_transitions()
        first = await gen.__anext__()
        second = await gen.__anext__()
        third = await gen.__anext__()

    assert (first[0], first[1]) == ("notepad", EventType.APP_FOCUS)
    assert (second[0], second[1]) == ("notepad", EventType.APP_BLUR)
    assert (third[0], third[1]) == ("chrome", EventType.APP_FOCUS)


@pytest.mark.asyncio
async def test_observe_skips_none_results():
    """_active_app_name returning None is silently ignored."""
    from jean.agent._windows import observe_app_transitions
    from jean.models import EventType

    # None → None → "excel"
    apps = iter([None, None, "excel"])

    def _next():
        try:
            return next(apps)
        except StopIteration:
            return "excel"

    with (
        patch("jean.agent._windows.ctypes"),
        patch("jean.agent._windows._active_app_name", side_effect=_next),
        patch("jean.agent._windows.asyncio.sleep", return_value=None),
    ):
        gen = observe_app_transitions()
        app, etype = await gen.__anext__()

    assert app == "excel"
    assert etype == EventType.APP_FOCUS
