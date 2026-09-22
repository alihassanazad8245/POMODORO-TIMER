"""Pure statistics functions over the session log.

No I/O here - session records go in, computed stats come out. This keeps the
logic trivially testable without touching the filesystem.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Sequence

from .models import PHASE_WORK, DailySummary, SessionRecord, StreakInfo, WeekComparison


def _work_sessions(sessions: Sequence[SessionRecord]) -> list[SessionRecord]:
    return [s for s in sessions if s.phase == PHASE_WORK]


def daily_summary(sessions: Sequence[SessionRecord], date: str) -> DailySummary:
    """Focus statistics for one specific ``YYYY-MM-DD`` date."""
    today_work = [s for s in _work_sessions(sessions) if s.date == date]
    today_breaks = [s for s in sessions if s.phase != PHASE_WORK and s.date == date]

    summary = DailySummary(date=date)
    summary.work_sessions = len(today_work)
    summary.completed_sessions = sum(1 for s in today_work if s.completed)
    summary.focus_minutes = round(sum(s.actual_minutes for s in today_work), 1)
    summary.break_minutes = round(sum(s.actual_minutes for s in today_breaks), 1)

    label_totals: Counter[str] = Counter()
    for s in today_work:
        if s.label:
            label_totals[s.label] += s.actual_minutes
    summary.labels = [(name, round(mins, 1)) for name, mins in label_totals.most_common(8)]
    return summary


def streaks(sessions: Sequence[SessionRecord]) -> StreakInfo:
    """Compute current/longest streaks of consecutive days with a completed
    work session, plus lifetime totals."""
    info = StreakInfo()
    completed_dates = sorted({
        s.date for s in _work_sessions(sessions) if s.completed and s.date
    })
    info.total_days_active = len(completed_dates)
    info.total_focus_minutes = round(sum(s.actual_minutes for s in _work_sessions(sessions)), 1)
    info.total_sessions = len(_work_sessions(sessions))

    if not completed_dates:
        return info

    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in completed_dates]
    longest = current_run = 1
    for prev, curr in zip(parsed, parsed[1:]):
        if (curr - prev).days == 1:
            current_run += 1
        elif (curr - prev).days > 1:
            longest = max(longest, current_run)
            current_run = 1
    longest = max(longest, current_run)
    info.longest_streak = longest

    today = date_cls.today()
    last_active = parsed[-1]
    gap = (today - last_active).days
    if gap > 1:
        info.current_streak = 0
    else:
        # Walk backward from the most recent active day counting the run.
        run = 1
        for i in range(len(parsed) - 1, 0, -1):
            if (parsed[i] - parsed[i - 1]).days == 1:
                run += 1
            else:
                break
        info.current_streak = run
    return info


def heatmap_data(
    sessions: Sequence[SessionRecord], weeks: int
) -> tuple[list[list[float]], date_cls, date_cls]:
    """Build a week-by-day grid of focus minutes for the last ``weeks`` weeks.

    Returns ``(grid, start_date, end_date)`` where ``grid`` is a list of
    weeks, each a list of 7 daily minute totals (Monday first), matching a
    GitHub-style contribution calendar. Days before the first tracked session
    and after today are included as 0-minute cells so the grid is rectangular.
    """
    totals: dict[str, float] = defaultdict(float)
    for s in _work_sessions(sessions):
        if s.date:
            totals[s.date] += s.actual_minutes

    end_date = date_cls.today()
    # Align the grid end to the end of this week (Sunday) and start `weeks`
    # weeks back, aligned to a Monday, like GitHub's contribution graph.
    end_of_week = end_date + timedelta(days=(6 - end_date.weekday()))
    start_date = end_of_week - timedelta(weeks=weeks - 1, days=6)

    grid: list[list[float]] = []
    cursor = start_date
    for _ in range(weeks):
        week = []
        for _day in range(7):
            week.append(round(totals.get(cursor.strftime("%Y-%m-%d"), 0.0), 1))
            cursor += timedelta(days=1)
        grid.append(week)
    return grid, start_date, end_date


def week_comparison(sessions: Sequence[SessionRecord]) -> WeekComparison:
    """Compare this Monday-to-Sunday week's focus time against last week's.

    Returns raw zeros with trend="no_data" when neither week has any
    sessions, so the caller can show an honest "nothing to compare yet"
    message instead of a misleading 0-vs-0 comparison.
    """
    today = date_cls.today()
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(weeks=1)

    def in_range(d: str, start: date_cls, end_exclusive: date_cls) -> bool:
        try:
            parsed = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            return False
        return start <= parsed < end_exclusive

    this_week = [s for s in _work_sessions(sessions)
                if in_range(s.date, this_monday, this_monday + timedelta(days=7))]
    last_week = [s for s in _work_sessions(sessions)
                if in_range(s.date, last_monday, this_monday)]

    result = WeekComparison(
        this_week_minutes=round(sum(s.actual_minutes for s in this_week), 1),
        last_week_minutes=round(sum(s.actual_minutes for s in last_week), 1),
        this_week_sessions=len(this_week),
        last_week_sessions=len(last_week),
        this_week_completed=sum(1 for s in this_week if s.completed),
        last_week_completed=sum(1 for s in last_week if s.completed),
    )

    if not this_week and not last_week:
        result.trend = "no_data"
    elif not last_week:
        result.trend = "new"
    else:
        delta = result.this_week_minutes - result.last_week_minutes
        result.change_percent = round((delta / result.last_week_minutes) * 100, 1)
        if abs(result.change_percent) < 1:
            result.trend = "flat"
        else:
            result.trend = "up" if delta > 0 else "down"
    return result


def recent_history(sessions: Sequence[SessionRecord], limit: int) -> list[SessionRecord]:
    """The most recent sessions (any phase), newest first."""
    ordered = sorted(sessions, key=lambda s: s.started_at, reverse=True)
    return ordered[:limit]
