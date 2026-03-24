"""macOS application transition capture via NSWorkspace.

This module requires pyobjc-framework-Cocoa:
    uv sync --extra macos

It should never be imported directly — AppTransitionCapture in capture.py
handles the ImportError fallback.

Implementation notes:
- NSWorkspace posts didActivateApplicationNotification on the main thread.
- We bridge to asyncio via a thread-safe queue.
- The NSRunLoop must spin on a background thread (not the asyncio event loop thread).

Privacy: only NSRunningApplication.localizedName is captured — never the
window title, document path, or any other personal data.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator

from jean.models import EventType

# This type alias avoids importing objc at module level in non-macOS tests
_AppFocusEvent = tuple[str, EventType]


async def observe_app_transitions() -> AsyncGenerator[_AppFocusEvent, None]:
    """Async generator that yields (app_name, EventType) on each focus change.

    Starts an NSRunLoop on a daemon thread and relays events to the
    asyncio event loop via asyncio.Queue.
    """
    try:
        import AppKit  # type: ignore[import]
        import objc  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "pyobjc is required for macOS capture. "
            "Install with: uv sync --extra macos"
        ) from exc

    queue: asyncio.Queue[_AppFocusEvent] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    class _Observer(AppKit.NSObject):  # type: ignore[misc]
        def appDidActivate_(self, notification: object) -> None:
            app = notification.userInfo().get(
                AppKit.NSWorkspaceApplicationKey
            )
            if app is not None:
                name = app.localizedName() or "unknown"
                loop.call_soon_threadsafe(
                    queue.put_nowait, (name, EventType.APP_FOCUS)
                )

        def appDidDeactivate_(self, notification: object) -> None:
            app = notification.userInfo().get(
                AppKit.NSWorkspaceApplicationKey
            )
            if app is not None:
                name = app.localizedName() or "unknown"
                loop.call_soon_threadsafe(
                    queue.put_nowait, (name, EventType.APP_BLUR)
                )

    def _run_runloop() -> None:
        observer = _Observer.alloc().init()
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserver_selector_name_object_(
            observer,
            objc.selector(observer.appDidActivate_, signature=b"v@:@"),
            AppKit.NSWorkspaceDidActivateApplicationNotification,
            None,
        )
        nc.addObserver_selector_name_object_(
            observer,
            objc.selector(observer.appDidDeactivate_, signature=b"v@:@"),
            AppKit.NSWorkspaceDidDeactivateApplicationNotification,
            None,
        )
        AppKit.NSRunLoop.currentRunLoop().run()

    thread = threading.Thread(target=_run_runloop, daemon=True)
    thread.start()

    while True:
        event = await queue.get()
        yield event
