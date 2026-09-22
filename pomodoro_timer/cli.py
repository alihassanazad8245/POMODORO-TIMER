"""Command-line interface: argument parsing, interactive menu, orchestration.

    python main.py                 interactive menu
    python main.py --start         start a session with saved/default durations
    python main.py --summary       today's focus summary
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date as date_cls
from pathlib import Path
from typing import Sequence

from . import __app_name__, __version__
from .config import (
    DEFAULT_HEATMAP_WEEKS,
    DEFAULT_HISTORY_LIMIT,
    MAX_MINUTES,
    MIN_MINUTES,
    Settings,
    TimerDefaults,
)
from .errors import InvalidInputError, PomodoroError
from .models import PHASE_LONG_BREAK, PHASE_SHORT_BREAK, PHASE_WORK, SessionRecord
from .notifier import notify
from .stats import daily_summary, heatmap_data, recent_history, streaks, week_comparison
from .storage import append_session, ensure_data_dir, load_config, load_sessions, save_config
from .timer import PhaseResult, run_phase
from .ui import UI

MIN_PYTHON = (3, 9)
logger = logging.getLogger("pomodoro_timer")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pomodoro-timer",
        description=f"{__app_name__} — a focus timer with streaks and a heatmap, in your terminal.",
        epilog=(
            "Examples:\n"
            "  python main.py\n"
            "  python main.py --start --label \"Write report\"\n"
            "  python main.py --start --work 50 --short-break 10 --cycles 3\n"
            "  python main.py --summary\n"
            "  python main.py --heatmap --weeks 16\n"
            "  python main.py --history --limit 20\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    actions = parser.add_argument_group("actions")
    actions.add_argument("--start", action="store_true", help="start a Pomodoro session")
    actions.add_argument("--summary", action="store_true", help="show today's focus summary")
    actions.add_argument("--heatmap", action="store_true", help="show the focus heatmap")
    actions.add_argument("--history", action="store_true", help="show recent session history")
    actions.add_argument("--compare", action="store_true",
                         help="compare this week's focus time against last week's")
    actions.add_argument("--set-defaults", action="store_true",
                         help="save --work/--short-break/--long-break/--cycles as new defaults")

    timing = parser.add_argument_group("session timing (used with --start or --set-defaults)")
    timing.add_argument("--work", type=int, metavar="MIN", help="work session length in minutes")
    timing.add_argument("--short-break", type=int, metavar="MIN", help="short break length in minutes")
    timing.add_argument("--long-break", type=int, metavar="MIN", help="long break length in minutes")
    timing.add_argument("--cycles", type=int, metavar="N",
                        help="work sessions before a long break")
    timing.add_argument("--label", metavar="TEXT", default="",
                        help="what you're working on (shown on the timer and in history)")
    timing.add_argument("--sessions", type=int, metavar="N", default=1,
                        help="how many work sessions to run this run (default: 1)")

    output = parser.add_argument_group("output")
    output.add_argument("--weeks", type=int, default=DEFAULT_HEATMAP_WEEKS,
                        help=f"weeks shown in --heatmap (default: {DEFAULT_HEATMAP_WEEKS})")
    output.add_argument("--limit", type=int, default=DEFAULT_HISTORY_LIMIT,
                        help=f"rows shown in --history (default: {DEFAULT_HISTORY_LIMIT})")
    output.add_argument("--no-color", action="store_true", help="disable coloured output")

    misc = parser.add_argument_group("misc")
    misc.add_argument("--verbose", "-v", action="store_true",
                      help="verbose logging and full tracebacks")
    misc.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _validate_minutes(value: int, field_name: str) -> int:
    if not (MIN_MINUTES <= value <= MAX_MINUTES):
        raise InvalidInputError(
            f"{field_name} must be between {MIN_MINUTES} and {MAX_MINUTES} minutes.",
        )
    return value


class Application:
    """Wires the UI, storage and timer engine together for one session."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ui = UI(no_color=settings.no_color)
        ensure_data_dir()
        self.defaults = load_config()

    # -- helpers ------------------------------------------------------- #

    def _record(self, result: PhaseResult) -> None:
        append_session(SessionRecord(
            phase=result.phase, label=result.label, planned_minutes=result.planned_minutes,
            actual_minutes=round(result.actual_seconds / 60, 2), completed=result.completed,
            started_at=result.started_at, ended_at=result.ended_at, date=result.date,
        ))

    def _notify_phase_end(self, phase: str, label: str) -> None:
        titles = {PHASE_WORK: "Focus session complete!", PHASE_SHORT_BREAK: "Break's over!",
                  PHASE_LONG_BREAK: "Long break's over!"}
        messages = {
            PHASE_WORK: f"Nice work on \"{label}\"." if label else "Nice work.",
            PHASE_SHORT_BREAK: "Back to it when you're ready.",
            PHASE_LONG_BREAK: "Ready for another round?",
        }
        notify(titles.get(phase, "Pomodoro Timer"), messages.get(phase, ""), console=self.ui.console)

    def run_session(self, work: int, short_break: int, long_break: int, cycles: int,
                    label: str, work_sessions: int) -> None:
        """Run a full Pomodoro cycle: work/break, repeating, long break every `cycles`."""
        self.ui.rule("SESSION STARTING")
        self.ui.info(f"Work {work} min → Short break {short_break} min "
                     f"(long break every {cycles} sessions)")

        for session_number in range(1, work_sessions + 1):
            work_result = run_phase(PHASE_WORK, work, label, self.ui.console)
            self._record(work_result)
            self._notify_phase_end(PHASE_WORK, label)

            if work_result.quit_requested:
                self.ui.session_quit()
                return
            if not work_result.completed:
                self.ui.phase_skipped("Focus session", work_result.actual_seconds / 60)
                continue

            if session_number >= work_sessions:
                self.ui.phase_complete("Focus session", work_result.actual_seconds / 60, "Done!")
                break

            is_long_break = session_number % cycles == 0
            break_phase = PHASE_LONG_BREAK if is_long_break else PHASE_SHORT_BREAK
            break_minutes = long_break if is_long_break else short_break
            next_label = "Long break" if is_long_break else "Short break"

            self.ui.phase_complete("Focus session", work_result.actual_seconds / 60, next_label)

            break_result = run_phase(break_phase, break_minutes, "", self.ui.console)
            self._record(break_result)
            self._notify_phase_end(break_phase, "")

            if break_result.quit_requested:
                self.ui.session_quit()
                return
            if not break_result.completed:
                self.ui.phase_skipped(next_label, break_result.actual_seconds / 60)

        self.ui.success(f"Session finished — {work_sessions} focus session(s) logged.")

    def show_summary(self) -> None:
        sessions = load_sessions()
        today = date_cls.today().strftime("%Y-%m-%d")
        self.ui.render_summary(daily_summary(sessions, today), streaks(sessions))

    def show_heatmap(self, weeks: int) -> None:
        sessions = load_sessions()
        grid, start, end = heatmap_data(sessions, weeks)
        self.ui.render_heatmap(grid, start, end)

    def show_history(self, limit: int) -> None:
        sessions = load_sessions()
        self.ui.render_history(recent_history(sessions, limit))

    def show_compare(self) -> None:
        sessions = load_sessions()
        self.ui.render_week_comparison(week_comparison(sessions))

    def show_settings(self) -> None:
        self.ui.render_settings(self.defaults)

    def update_defaults(self, work: int | None, short_break: int | None,
                        long_break: int | None, cycles: int | None) -> None:
        if work is not None:
            self.defaults.work_minutes = _validate_minutes(work, "Work duration")
        if short_break is not None:
            self.defaults.short_break_minutes = _validate_minutes(short_break, "Short break duration")
        if long_break is not None:
            self.defaults.long_break_minutes = _validate_minutes(long_break, "Long break duration")
        if cycles is not None:
            if cycles < 1:
                raise InvalidInputError("Cycles before a long break must be at least 1.")
            self.defaults.cycles_before_long_break = cycles
        save_config(self.defaults)
        self.ui.success("Defaults saved.")
        self.show_settings()

    # -- interactive menu ---------------------------------------------- #

    def _ask(self, prompt: str) -> str:
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            self.ui.goodbye()
            raise SystemExit(0)

    def _ask_int(self, prompt: str, default: int) -> int:
        raw = self._ask(f"{prompt} [{default}]: ")
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            self.ui.warn(f"Not a number, using default ({default}).")
            return default

    def interactive(self) -> int:
        self.ui.banner()
        self.ui.info("No account, no cloud sync — everything stays in this project's data/ folder.")

        menu = (
            "\n[bold bright_red]MAIN MENU[/bold bright_red]\n"
            "  [bold]1[/bold]  Start a Pomodoro session\n"
            "  [bold]2[/bold]  View today's summary\n"
            "  [bold]3[/bold]  View focus heatmap\n"
            "  [bold]4[/bold]  Compare this week vs last week\n"
            "  [bold]5[/bold]  View session history\n"
            "  [bold]6[/bold]  Settings\n"
            "  [bold]7[/bold]  Exit\n"
        )

        while True:
            self.ui.console.print(menu)
            choice = self._ask("Select an option [1-7]: ")
            try:
                if choice == "1":
                    work = self._ask_int("Work minutes", self.defaults.work_minutes)
                    short_break = self._ask_int("Short break minutes", self.defaults.short_break_minutes)
                    long_break = self._ask_int("Long break minutes", self.defaults.long_break_minutes)
                    cycles = self._ask_int("Sessions before a long break", self.defaults.cycles_before_long_break)
                    sessions_count = self._ask_int("How many work sessions this run", 1)
                    label = self._ask("What are you working on? (optional): ")
                    self.run_session(
                        _validate_minutes(work, "Work duration"),
                        _validate_minutes(short_break, "Short break duration"),
                        _validate_minutes(long_break, "Long break duration"),
                        max(1, cycles), label, max(1, sessions_count),
                    )
                elif choice == "2":
                    self.show_summary()
                elif choice == "3":
                    weeks = self._ask_int("Weeks to show", DEFAULT_HEATMAP_WEEKS)
                    self.show_heatmap(max(1, weeks))
                elif choice == "4":
                    self.show_compare()
                elif choice == "5":
                    limit = self._ask_int("How many sessions to show", DEFAULT_HISTORY_LIMIT)
                    self.show_history(max(1, limit))
                elif choice == "6":
                    self.show_settings()
                    if self._ask("Change defaults? (y/N): ").lower() == "y":
                        work = self._ask_int("Work minutes", self.defaults.work_minutes)
                        short_break = self._ask_int("Short break minutes", self.defaults.short_break_minutes)
                        long_break = self._ask_int("Long break minutes", self.defaults.long_break_minutes)
                        cycles = self._ask_int("Sessions before a long break",
                                               self.defaults.cycles_before_long_break)
                        self.update_defaults(work, short_break, long_break, cycles)
                elif choice in ("7", "q", "quit", "exit"):
                    self.ui.goodbye()
                    return 0
                else:
                    self.ui.warn("Please choose a number between 1 and 7.")
            except PomodoroError as exc:
                self.ui.error(exc)
                if self.settings.verbose:
                    self.ui.console.print_exception()


def _check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        required = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        sys.stderr.write(
            f"[ERROR] {__app_name__} requires Python {required} or newer (found {current}).\n"
        )
        raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> int:
    """Program entry point. Returns a process exit code."""
    _check_python_version()

    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    settings = Settings(no_color=args.no_color, verbose=args.verbose)
    app = Application(settings)
    ui = app.ui

    try:
        if args.set_defaults:
            app.update_defaults(args.work, args.short_break, args.long_break, args.cycles)
            return 0

        direct = bool(args.start or args.summary or args.heatmap or args.history or args.compare)
        if args.start:
            ui.banner()
        elif direct:
            ui.mini_header()

        if args.start:
            work = _validate_minutes(args.work, "Work duration") if args.work is not None else app.defaults.work_minutes
            short_break = (_validate_minutes(args.short_break, "Short break duration")
                          if args.short_break is not None else app.defaults.short_break_minutes)
            long_break = (_validate_minutes(args.long_break, "Long break duration")
                         if args.long_break is not None else app.defaults.long_break_minutes)
            cycles = args.cycles if args.cycles is not None else app.defaults.cycles_before_long_break
            if cycles < 1:
                raise InvalidInputError("Cycles before a long break must be at least 1.")
            app.run_session(work, short_break, long_break, cycles, args.label, max(1, args.sessions))
        if args.summary:
            app.show_summary()
        if args.heatmap:
            app.show_heatmap(max(1, args.weeks))
        if args.history:
            app.show_history(max(1, args.limit))
        if args.compare:
            app.show_compare()

        if not direct:
            return app.interactive()
        return 0

    except PomodoroError as exc:
        ui.error(exc)
        if args.verbose:
            ui.console.print_exception()
        return 1
    except KeyboardInterrupt:
        ui.console.print("\n[yellow]Cancelled by user.[/yellow]")
        return 130
    except Exception as exc:  # noqa: BLE001 - last line of defence
        ui.error(
            "An unexpected internal error occurred.",
            hints=(f"Details: {type(exc).__name__}: {exc}",
                  "Re-run with --verbose to see the full traceback"),
        )
        if args.verbose:
            ui.console.print_exception()
        return 1
