"""Tests for jean/agent/_linux.py — Linux app-transition capture."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeProc:
    """Simulates /proc/{pid}/comm via a fake Path.exists() / read_text()."""

    def __init__(self, comm: str) -> None:
        self._comm = comm

    def exists(self) -> bool:
        return True

    def read_text(self) -> str:
        return self._comm + "\n"


def _make_check_output(wid: str, pid: str) -> MagicMock:
    """Return a check_output mock that returns wid, then pid on successive calls."""
    side_effects = [
        wid.encode(),   # xdotool getactivewindow
        pid.encode(),   # xdotool getwindowpid <wid>
    ]

    def _side(args, **_kw):
        # xdotool --version check returns immediately
        if "--version" in args:
            return b"xdotool version 3.20160805.1"
        return side_effects.pop(0)

    m = MagicMock(side_effect=_side)
    return m


# ---------------------------------------------------------------------------
# _active_app_name
# ---------------------------------------------------------------------------

def test_active_app_name_returns_process_name():
    """Happy path: xdotool resolves window → pid → comm."""
    from jean.agent._linux import _active_app_name

    with (
        patch("jean.agent._linux.subprocess.check_output") as mock_co,
        patch("jean.agent._linux.Path") as mock_path,
    ):
        mock_co.side_effect = lambda args, **_kw: (
            b"12345\n" if "getactivewindow" in args else b"9999\n"
        )
        mock_path.return_value = _FakeProc("firefox")

        result = _active_app_name()

    assert result == "firefox"


def test_active_app_name_returns_none_on_subprocess_error():
    """CalledProcessError → returns None gracefully."""
    from jean.agent._linux import _active_app_name
    import subprocess

    with patch(
        "jean.agent._linux.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "xdotool"),
    ):
        assert _active_app_name() is None


def test_active_app_name_returns_none_when_xdotool_missing():
    """FileNotFoundError → returns None gracefully."""
    from jean.agent._linux import _active_app_name

    with patch(
        "jean.agent._linux.subprocess.check_output",
        side_effect=FileNotFoundError,
    ):
        assert _active_app_name() is None


# ---------------------------------------------------------------------------
# observe_app_transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_observe_raises_import_error_when_xdotool_missing():
    """ImportError raised when xdotool binary not found."""
    from jean.agent._linux import observe_app_transitions

    with patch(
        "jean.agent._linux.subprocess.check_output",
        side_effect=FileNotFoundError,
    ):
        gen = observe_app_transitions()
        with pytest.raises(ImportError, match="xdotool"):
            await gen.__anext__()


@pytest.mark.asyncio
async def test_observe_yields_focus_on_first_app():
    """First active app → APP_FOCUS only (no preceding blur)."""
    from jean.agent._linux import observe_app_transitions
    from jean.models import EventType

    call_count = 0

    def _mock_co(args, **_kw):
        nonlocal call_count
        call_count += 1
        if "--version" in args:
            return b"xdotool 3.x"
        if "getactivewindow" in args:
            return b"111\n"
        return b"42\n"

    with (
        patch("jean.agent._linux.subprocess.check_output", side_effect=_mock_co),
        patch("jean.agent._linux.Path", return_value=_FakeProc("gedit")),
        patch("jean.agent._linux.asyncio.sleep", return_value=None),
    ):
        gen = observe_app_transitions()
        app_name, event_type = await gen.__anext__()

    assert app_name == "gedit"
    assert event_type == EventType.APP_FOCUS


@pytest.mark.asyncio
async def test_observe_yields_blur_then_focus_on_transition():
    """App change → (old, APP_BLUR) then (new, APP_FOCUS)."""
    from jean.agent._linux import observe_app_transitions
    from jean.models import EventType

    apps = iter(["gedit", "gedit", "firefox"])  # first call init, second same, third change

    def _active():
        try:
            return next(apps)
        except StopIteration:
            return "firefox"

    with (
        patch("jean.agent._linux.subprocess.check_output", return_value=b"xdotool 3.x"),
        patch("jean.agent._linux._active_app_name", side_effect=_active),
        patch("jean.agent._linux.asyncio.sleep", return_value=None),
    ):
        gen = observe_app_transitions()
        first_app, first_type = await gen.__anext__()
        # next call returns same app — no event
        # third call returns new app → blur + focus
        second_app, second_type = await gen.__anext__()
        third_app, third_type = await gen.__anext__()

    assert (first_app, first_type) == ("gedit", EventType.APP_FOCUS)
    assert (second_app, second_type) == ("gedit", EventType.APP_BLUR)
    assert (third_app, third_type) == ("firefox", EventType.APP_FOCUS)
