"""Cross-platform, non-blocking single-key polling.

Used by the timer to let the user press ``p`` (pause/resume), ``s`` (skip
phase), or ``q`` (quit) while a countdown is running, without blocking the
countdown itself. Windows uses ``msvcrt``; POSIX systems use ``termios`` +
``select`` in cbreak mode. If standard input isn't a real terminal (piped
input, a test harness, a non-interactive run), polling silently no-ops
instead of raising - keyboard control is a convenience, never a requirement.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator

_IS_WINDOWS = sys.platform.startswith("win")

if _IS_WINDOWS:
    import msvcrt
else:
    try:
        import select
        import termios
        import tty
    except ImportError:  # pragma: no cover - exotic platform with neither
        select = termios = tty = None  # type: ignore[assignment]


def keyboard_available() -> bool:
    """Whether interactive single-key polling is possible right now."""
    if _IS_WINDOWS:
        return True
    if termios is None:
        return False
    try:
        return sys.stdin.isatty()
    except Exception:  # noqa: BLE001
        return False


@contextmanager
def raw_mode() -> Iterator[None]:
    """Put the POSIX terminal into cbreak mode for the duration of the block.

    A no-op on Windows (msvcrt needs no mode change) and a no-op anywhere
    standard input isn't a real interactive terminal.
    """
    if _IS_WINDOWS or not keyboard_available():
        yield
        return

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def poll_key() -> str | None:
    """Return one lowercase key pressed since the last call, or None.

    Never blocks. Safe to call every tick of a countdown loop.
    """
    if _IS_WINDOWS:
        if msvcrt.kbhit():
            try:
                ch = msvcrt.getch()
                return ch.decode(errors="ignore").lower()
            except Exception:  # noqa: BLE001
                return None
        return None

    if not keyboard_available():
        return None
    try:
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if ready:
            return sys.stdin.read(1).lower()
    except Exception:  # noqa: BLE001
        return None
    return None
