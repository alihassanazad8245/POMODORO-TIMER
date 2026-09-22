"""Typed data structures for sessions and computed statistics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

PHASE_WORK = "work"
PHASE_SHORT_BREAK = "short_break"
PHASE_LONG_BREAK = "long_break"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class SessionRecord:
    """One completed, skipped, or quit timer phase.

    ``actual_minutes`` is real elapsed focus/break time even if the phase was
    skipped early - partial focus still counts. ``completed`` is True only
    when the phase ran its full planned duration.
    """

    phase: str
    label: str
    planned_minutes: int
    actual_minutes: float
    completed: bool
    started_at: str
    ended_at: str
    date: str  # YYYY-MM-DD, local date the session started on

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionRecord":
        return cls(
            phase=data.get("phase", PHASE_WORK),
            label=data.get("label", ""),
            planned_minutes=int(data.get("planned_minutes", 0)),
            actual_minutes=float(data.get("actual_minutes", 0.0)),
            completed=bool(data.get("completed", False)),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            date=data.get("date", ""),
        )


@dataclass(slots=True)
class DailySummary:
    """Focus statistics for a single calendar date."""

    date: str
    focus_minutes: float = 0.0
    work_sessions: int = 0
    completed_sessions: int = 0
    break_minutes: float = 0.0
    labels: list[tuple[str, float]] = field(default_factory=list)


@dataclass(slots=True)
class StreakInfo:
    """Consecutive-day focus streaks, based on any completed work session."""

    current_streak: int = 0
    longest_streak: int = 0
    total_days_active: int = 0
    total_focus_minutes: float = 0.0
    total_sessions: int = 0


@dataclass(slots=True)
class WeekComparison:
    """This week vs. last week, Monday-to-Sunday."""

    this_week_minutes: float = 0.0
    last_week_minutes: float = 0.0
    this_week_sessions: int = 0
    last_week_sessions: int = 0
    this_week_completed: int = 0
    last_week_completed: int = 0
    change_percent: float | None = None  # None when last week has no data to compare against
    trend: str = "no_data"  # "up", "down", "flat", "new", or "no_data"
