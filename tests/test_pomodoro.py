"""Test suite for Pomodoro Timer.

Storage tests use tmp_path so nothing touches the real data/ folder. The
timer test uses a tiny tick so the live countdown loop finishes instantly.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from rich.console import Console

from pomodoro_timer.config import MAX_MINUTES, MIN_MINUTES, TimerDefaults
from pomodoro_timer.errors import InvalidInputError, PomodoroError
from pomodoro_timer.models import (
    PHASE_LONG_BREAK,
    PHASE_SHORT_BREAK,
    PHASE_WORK,
    SessionRecord,
)
from pomodoro_timer.stats import daily_summary, heatmap_data, recent_history, streaks, week_comparison
from pomodoro_timer.storage import append_session, load_config, load_sessions, save_config
from pomodoro_timer.timer import run_phase

# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def _record(date_str: str, minutes: float = 25.0, completed: bool = True,
           phase: str = PHASE_WORK, label: str = "") -> SessionRecord:
    return SessionRecord(
        phase=phase, label=label, planned_minutes=25, actual_minutes=minutes,
        completed=completed, started_at=f"{date_str}T10:00:00+00:00",
        ended_at=f"{date_str}T10:25:00+00:00", date=date_str,
    )


def test_load_sessions_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_sessions(tmp_path / "nope.json") == []


def test_load_sessions_corrupted_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_sessions(path) == []


def test_append_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    append_session(_record("2026-09-01"), path)
    append_session(_record("2026-09-02", minutes=12.5, completed=False), path)
    loaded = load_sessions(path)
    assert len(loaded) == 2
    assert loaded[0].date == "2026-09-01"
    assert loaded[1].actual_minutes == 12.5
    assert loaded[1].completed is False


def test_append_writes_valid_json_atomically(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    append_session(_record("2026-09-01"), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 1


def test_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    defaults = TimerDefaults(work_minutes=50, short_break_minutes=10,
                             long_break_minutes=20, cycles_before_long_break=3)
    save_config(defaults, path)
    loaded = load_config(path)
    assert loaded.work_minutes == 50
    assert loaded.cycles_before_long_break == 3


def test_load_config_missing_file_returns_builtin_defaults(tmp_path: Path) -> None:
    defaults = load_config(tmp_path / "nope.json")
    assert defaults.work_minutes == 25
    assert defaults.short_break_minutes == 5


def test_load_config_corrupted_file_returns_builtin_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("not json", encoding="utf-8")
    defaults = load_config(path)
    assert defaults.work_minutes == 25


def test_timer_defaults_from_dict_ignores_invalid_values() -> None:
    defaults = TimerDefaults.from_dict({"work_minutes": -5, "cycles_before_long_break": "x"})
    assert defaults.work_minutes == 25  # invalid negative rejected, built-in kept
    assert defaults.cycles_before_long_break == 4


# --------------------------------------------------------------------------- #
# Stats: daily summary
# --------------------------------------------------------------------------- #


def test_daily_summary_aggregates_focus_and_breaks() -> None:
    sessions = [
        _record("2026-09-01", minutes=25.0, label="Report"),
        _record("2026-09-01", minutes=20.0, completed=False, label="Report"),
        _record("2026-09-01", minutes=5.0, phase=PHASE_SHORT_BREAK),
        _record("2026-09-02", minutes=25.0),  # different day, excluded
    ]
    summary = daily_summary(sessions, "2026-09-01")
    assert summary.work_sessions == 2
    assert summary.completed_sessions == 1
    assert summary.focus_minutes == 45.0
    assert summary.break_minutes == 5.0
    assert summary.labels == [("Report", 45.0)]


def test_daily_summary_empty_day() -> None:
    summary = daily_summary([], "2026-09-01")
    assert summary.work_sessions == 0
    assert summary.focus_minutes == 0.0
    assert summary.labels == []


# --------------------------------------------------------------------------- #
# Stats: streaks
# --------------------------------------------------------------------------- #


def test_streaks_empty_history() -> None:
    info = streaks([])
    assert info.current_streak == 0
    assert info.longest_streak == 0
    assert info.total_days_active == 0


def test_streaks_consecutive_days_ending_today() -> None:
    today = date.today()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]  # today, -1, -2
    sessions = [_record(d) for d in dates]
    info = streaks(sessions)
    assert info.current_streak == 3
    assert info.longest_streak == 3
    assert info.total_days_active == 3


def test_streaks_broken_by_gap() -> None:
    today = date.today()
    old_dates = [(today - timedelta(days=10 + i)).strftime("%Y-%m-%d") for i in range(4)]
    sessions = [_record(d) for d in old_dates]
    info = streaks(sessions)
    assert info.longest_streak == 4
    assert info.current_streak == 0  # last active day is far in the past


def test_streaks_ignores_incomplete_sessions() -> None:
    today = date.today().strftime("%Y-%m-%d")
    sessions = [_record(today, completed=False)]
    info = streaks(sessions)
    assert info.current_streak == 0
    assert info.total_days_active == 0
    # Lifetime totals still count every work session, completed or not.
    assert info.total_sessions == 1


# --------------------------------------------------------------------------- #
# Stats: heatmap
# --------------------------------------------------------------------------- #


def test_heatmap_grid_shape() -> None:
    grid, start, end = heatmap_data([], weeks=4)
    assert len(grid) == 4
    assert all(len(week) == 7 for week in grid)
    assert end == date.today()


def test_heatmap_places_minutes_on_correct_day() -> None:
    today = date.today().strftime("%Y-%m-%d")
    sessions = [_record(today, minutes=42.0)]
    grid, start, end = heatmap_data(sessions, weeks=2)
    assert sum(sum(week) for week in grid) == 42.0


def test_heatmap_start_is_a_monday() -> None:
    _, start, _ = heatmap_data([], weeks=4)
    assert start.weekday() == 0  # Monday


# --------------------------------------------------------------------------- #
# Stats: history
# --------------------------------------------------------------------------- #


def test_recent_history_orders_newest_first_and_respects_limit() -> None:
    sessions = [_record("2026-09-01"), _record("2026-09-03"), _record("2026-09-02")]
    for s, hh in zip(sessions, ["10", "12", "11"]):
        s.started_at = f"{s.date}T{hh}:00:00+00:00"
    result = recent_history(sessions, limit=2)
    assert len(result) == 2
    assert result[0].date == "2026-09-03"


# --------------------------------------------------------------------------- #
# Stats: week comparison
# --------------------------------------------------------------------------- #


def test_week_comparison_no_data_at_all() -> None:
    result = week_comparison([])
    assert result.trend == "no_data"
    assert result.change_percent is None


def test_week_comparison_new_when_only_this_week_has_data() -> None:
    today = date.today().strftime("%Y-%m-%d")
    sessions = [_record(today, minutes=25.0)]
    result = week_comparison(sessions)
    assert result.trend == "new"
    assert result.this_week_minutes == 25.0
    assert result.last_week_minutes == 0.0
    assert result.change_percent is None


def test_week_comparison_detects_upward_trend() -> None:
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(weeks=1)
    sessions = [
        _record(this_monday.strftime("%Y-%m-%d"), minutes=100.0),
        _record(last_monday.strftime("%Y-%m-%d"), minutes=50.0),
    ]
    result = week_comparison(sessions)
    assert result.trend == "up"
    assert result.change_percent == 100.0


def test_week_comparison_detects_downward_trend() -> None:
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(weeks=1)
    sessions = [
        _record(this_monday.strftime("%Y-%m-%d"), minutes=25.0),
        _record(last_monday.strftime("%Y-%m-%d"), minutes=100.0),
    ]
    result = week_comparison(sessions)
    assert result.trend == "down"
    assert result.change_percent == -75.0


def test_week_comparison_excludes_sessions_outside_the_two_week_window() -> None:
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    three_weeks_ago = (this_monday - timedelta(weeks=3)).strftime("%Y-%m-%d")
    sessions = [_record(three_weeks_ago, minutes=999.0)]
    result = week_comparison(sessions)
    assert result.trend == "no_data"
    assert result.this_week_minutes == 0.0
    assert result.last_week_minutes == 0.0


# --------------------------------------------------------------------------- #
# Timer engine
# --------------------------------------------------------------------------- #


def test_run_phase_completes_naturally() -> None:
    console = Console(file=open("/dev/null", "w") if _has_dev_null() else None)
    result = run_phase(PHASE_WORK, 1, "unit test", console, tick=0.001)
    assert result.completed is True
    assert result.quit_requested is False
    assert result.phase == PHASE_WORK
    assert result.label == "unit test"
    assert 55 <= result.actual_seconds <= 65


def _has_dev_null() -> bool:
    try:
        open("/dev/null", "w").close()
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Notifier (fallback path only - no real OS calls in tests)
# --------------------------------------------------------------------------- #


def test_notify_falls_back_without_crashing_on_non_windows() -> None:
    from pomodoro_timer.notifier import notify

    # On this test platform (not Windows), notify() must fall back cleanly.
    result = notify("Test title", "Test message")
    assert result is False  # no real OS toast fired


def test_beep_never_raises() -> None:
    from pomodoro_timer.notifier import beep

    beep()  # should not raise even without a real terminal


# --------------------------------------------------------------------------- #
# Keyboard module safety
# --------------------------------------------------------------------------- #


def test_poll_key_is_safe_without_a_tty() -> None:
    from pomodoro_timer import keyboard

    # In a test harness, stdin is not an interactive terminal.
    assert keyboard.poll_key() is None


def test_raw_mode_is_a_safe_noop_without_a_tty() -> None:
    from pomodoro_timer import keyboard

    with keyboard.raw_mode():
        pass  # must not raise


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_parser_accepts_documented_flags() -> None:
    from pomodoro_timer.cli import build_parser

    args = build_parser().parse_args(
        ["--start", "--work", "50", "--short-break", "10", "--cycles", "3", "--label", "Deep work"]
    )
    assert args.start is True
    assert args.work == 50
    assert args.label == "Deep work"


def test_cli_summary_flag_runs_without_error(tmp_path: Path, monkeypatch) -> None:
    from pomodoro_timer import storage as storage_module
    monkeypatch.setattr(storage_module, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(storage_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(storage_module, "DATA_DIR", tmp_path)

    from pomodoro_timer.cli import main
    assert main(["--summary", "--no-color"]) == 0


def test_cli_compare_flag_runs_without_error(tmp_path: Path, monkeypatch) -> None:
    from pomodoro_timer import storage as storage_module
    monkeypatch.setattr(storage_module, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(storage_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(storage_module, "DATA_DIR", tmp_path)

    from pomodoro_timer.cli import main
    assert main(["--compare", "--no-color"]) == 0


def test_validate_minutes_rejects_out_of_range() -> None:
    from pomodoro_timer.cli import _validate_minutes

    with pytest.raises(InvalidInputError):
        _validate_minutes(0, "Work duration")
    with pytest.raises(InvalidInputError):
        _validate_minutes(MAX_MINUTES + 1, "Work duration")
    assert _validate_minutes(MIN_MINUTES, "Work duration") == MIN_MINUTES
