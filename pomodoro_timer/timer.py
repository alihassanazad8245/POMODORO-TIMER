"""The countdown engine.

Runs one timer phase (work, short break, or long break) with a live terminal
display, polling the keyboard every tick so the user can pause, skip, or quit
without waiting for the phase to end. Contains no storage or notification
logic itself - :mod:`.cli` wires those in via the returned :class:`PhaseResult`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from . import keyboard
from .models import PHASE_LONG_BREAK, PHASE_SHORT_BREAK, PHASE_WORK

PHASE_TITLES = {
    PHASE_WORK: "🍅 FOCUS SESSION",
    PHASE_SHORT_BREAK: "☕ SHORT BREAK",
    PHASE_LONG_BREAK: "🌿 LONG BREAK",
}
PHASE_COLORS = {
    PHASE_WORK: "bright_red",
    PHASE_SHORT_BREAK: "bright_cyan",
    PHASE_LONG_BREAK: "bright_green",
}


@dataclass(slots=True)
class PhaseResult:
    """Outcome of one countdown phase."""

    phase: str
    label: str
    planned_minutes: int
    actual_seconds: float
    completed: bool
    started_at: str
    ended_at: str
    date: str
    quit_requested: bool = False


def _format_clock(seconds_left: float) -> str:
    total = max(0, int(round(seconds_left)))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def run_phase(
    phase: str, minutes: int, label: str, console: Console, tick: float = 1.0
) -> PhaseResult:
    """Run one countdown phase with a live display and keyboard controls.

    ``tick`` controls the display refresh / keyboard poll interval in
    seconds; tests pass a tiny value so the whole loop finishes instantly.
    """
    total_seconds = minutes * 60
    started_dt = datetime.now(timezone.utc)
    start_monotonic = time.monotonic()
    paused = False
    paused_elapsed = 0.0
    pause_started: float | None = None
    quit_requested = False
    completed = False
    elapsed = 0.0

    color = PHASE_COLORS.get(phase, "white")
    title = PHASE_TITLES.get(phase, phase.upper())

    def render(remaining: float) -> Panel:
        header = Text()
        header.append(f"{title}\n\n", style=f"bold {color}")
        if label:
            header.append(f"{label}\n", style="italic white")

        clock = Text(_format_clock(remaining), style=f"bold {color}", justify="center")

        footer = Text()
        state = "PAUSED" if paused else "running"
        footer.append(f"\n\n[{state}]  ", style="yellow" if paused else "dim white")
        footer.append("p pause/resume   s skip   q quit", style="dim white")

        return Panel(Group(header, clock, footer), border_style=color, padding=(1, 4))

    with keyboard.raw_mode(), Live(render(total_seconds), console=console, refresh_per_second=4,
                                    transient=False) as live:
        while True:
            key = keyboard.poll_key()
            if key == "q":
                quit_requested = True
                break
            if key == "s":
                break
            if key == "p":
                if paused:
                    paused_elapsed += time.monotonic() - (pause_started or time.monotonic())
                    pause_started = None
                    paused = False
                else:
                    pause_started = time.monotonic()
                    paused = True

            if paused:
                elapsed = (pause_started or time.monotonic()) - start_monotonic - paused_elapsed
            else:
                elapsed = time.monotonic() - start_monotonic - paused_elapsed

            remaining = total_seconds - elapsed
            live.update(render(max(0.0, remaining)))

            if not paused and remaining <= 0:
                completed = True
                elapsed = total_seconds
                break

            time.sleep(tick)

        final_elapsed = float(total_seconds) if completed else elapsed

    ended_dt = datetime.now(timezone.utc)
    return PhaseResult(
        phase=phase, label=label, planned_minutes=minutes,
        actual_seconds=max(0.0, final_elapsed), completed=completed,
        started_at=started_dt.isoformat(timespec="seconds"),
        ended_at=ended_dt.isoformat(timespec="seconds"),
        date=started_dt.astimezone().strftime("%Y-%m-%d"),
        quit_requested=quit_requested,
    )
