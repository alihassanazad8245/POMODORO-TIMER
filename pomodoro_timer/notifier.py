"""Desktop notifications.

On Windows, this fires a real toast notification via ``winotify``. On any
other platform, or if the toast fails for any reason (no display, missing
permission, etc.), it falls back to a loud in-terminal alert plus the
terminal bell - notifications are a bonus, never a requirement for the timer
to work correctly.
"""

from __future__ import annotations

import logging
import platform
import sys

from .config import NOTIFIER_APP_ID

logger = logging.getLogger(__name__)


def _try_windows_toast(title: str, message: str) -> bool:
    """Attempt a real Windows toast notification. Returns True on success."""
    if platform.system() != "Windows":
        return False
    try:
        from winotify import Notification  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("winotify not installed; falling back to terminal alert")
        return False

    try:
        toast = Notification(app_id=NOTIFIER_APP_ID, title=title, msg=message, duration="short")
        toast.show()
        return True
    except Exception as exc:  # noqa: BLE001 - a failed toast must never crash the timer
        logger.debug("Windows toast failed: %s", exc)
        return False


def beep() -> None:
    """Ring the terminal bell, if the terminal supports it."""
    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def notify(title: str, message: str, console=None) -> bool:
    """Send a desktop notification, falling back to a terminal panel.

    Returns True if a real OS toast was shown, False if only the terminal
    fallback fired (the caller can use this to avoid double-announcing).
    """
    beep()
    if _try_windows_toast(title, message):
        return True

    if console is not None:
        from rich.panel import Panel
        from rich.text import Text

        body = Text()
        body.append(f"{title}\n", style="bold white")
        body.append(message, style="white")
        console.print(Panel(body, border_style="bright_red", title="[bold]🔔 ALERT[/bold]"))
    return False
