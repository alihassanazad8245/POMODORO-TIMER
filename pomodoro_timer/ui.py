"""Terminal presentation layer built on ``rich``."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta
from typing import Sequence

from rich.align import Align
from rich.box import HEAVY, ROUNDED
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import __app_name__, __author__, __instagram__, __tagline__, __version__
from .errors import PomodoroError
from .models import PHASE_WORK, DailySummary, SessionRecord, StreakInfo, WeekComparison
from .utils import bar

BANNER = r"""
  ██████╗  ██████╗ ███╗   ███╗ ██████╗ ██████╗  ██████╗ ██████╗  ██████╗
  ██╔══██╗██╔═══██╗████╗ ████║██╔═══██╗██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗
  ██████╔╝██║   ██║██╔████╔██║██║   ██║██║  ██║██║   ██║██████╔╝██║   ██║
  ██╔═══╝ ██║   ██║██║╚██╔╝██║██║   ██║██║  ██║██║   ██║██╔══██╗██║   ██║
  ██║     ╚██████╔╝██║ ╚═╝ ██║╚██████╔╝██████╔╝╚██████╔╝██║  ██║╚██████╔╝
  ╚═╝      ╚═════╝ ╚═╝     ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝ ╚═════╝
                          🍅  T I M E R
"""

_HEATMAP_LEVELS = [
    (0, "grey35"),
    (1, "dark_red"),
    (25, "red3"),
    (50, "orange_red1"),
    (100, "gold1"),
]
_WEEKDAY_LABELS = ["Mon", "", "Wed", "", "Fri", "", ""]
_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _heatmap_color(minutes: float) -> str:
    color = _HEATMAP_LEVELS[0][1]
    for threshold, name in _HEATMAP_LEVELS:
        if minutes >= threshold:
            color = name
    return color


class UI:
    """All terminal output flows through this class."""

    def __init__(self, no_color: bool = False) -> None:
        self.console = Console(no_color=no_color, highlight=False, soft_wrap=False)
        self.no_color = no_color

    # ------------------------------------------------------------------ #
    # Generic messages
    # ------------------------------------------------------------------ #

    def banner(self) -> None:
        header = Text(BANNER.strip("\n"), style="bold bright_red" if not self.no_color else "")
        subtitle = Text.assemble(
            (f"{__app_name__} ", "bold white"),
            (f"v{__version__}", "dim"),
            ("  •  ", "dim"),
            (__tagline__, "italic bright_red"),
        )
        self.console.print(
            Panel(Group(Align.center(header), Align.center(subtitle)),
                  box=HEAVY, border_style="bright_red", padding=(0, 2))
        )

    def mini_header(self) -> None:
        """A compact one-line header for routine data views (summary, heatmap,
        history, compare) - so checking your stats doesn't reprint the full
        ASCII banner every single time."""
        self.console.print(
            f"[bold bright_red]🍅 {__app_name__}[/bold bright_red] "
            f"[dim]v{__version__}[/dim]"
        )

    def rule(self, title: str) -> None:
        self.console.print()
        self.console.print(Rule(f"[bold bright_red]{title}[/bold bright_red]", style="bright_red"))

    def success(self, message: str) -> None:
        self.console.print(f"[bold green]\\[OK][/bold green] {message}")

    def info(self, message: str) -> None:
        self.console.print(f"[bold blue]\\[i][/bold blue] {message}")

    def warn(self, message: str) -> None:
        self.console.print(f"[bold yellow]\\[!][/bold yellow] {message}")

    def error(self, error: PomodoroError | str, hints: Sequence[str] = ()) -> None:
        if isinstance(error, PomodoroError):
            message, hint_list = error.message, list(error.hints)
        else:
            message, hint_list = str(error), list(hints)

        body = Text(message, style="bold red")
        if hint_list:
            body.append("\n\nPlease check:\n", style="white")
            for hint in hint_list:
                body.append(f"  • {hint}\n", style="dim white")

        self.console.print(Panel(body, title="[bold red]ERROR[/bold red]",
                                  border_style="red", box=ROUNDED))

    def goodbye(self) -> None:
        text = Text()
        text.append("Stay focused, see you next session! 🍅\n", style="bold bright_red")
        text.append(f"Built by {__author__}  ", style="white")
        text.append(f"· Instagram: @{__instagram__}", style="dim cyan")
        self.console.print()
        self.console.print(Panel(text, box=ROUNDED, border_style="bright_red", padding=(0, 2)))

    # ------------------------------------------------------------------ #
    # Phase transitions
    # ------------------------------------------------------------------ #

    def phase_complete(self, phase_label: str, minutes: float, next_label: str) -> None:
        body = Text()
        body.append(f"{phase_label} finished ", style="bold green")
        body.append(f"({minutes:.1f} min)\n", style="dim white")
        body.append(f"Next up: {next_label}", style="white")
        self.console.print(Panel(body, border_style="green", box=ROUNDED))

    def phase_skipped(self, phase_label: str, minutes: float) -> None:
        self.warn(f"{phase_label} skipped after {minutes:.1f} min.")

    def session_quit(self) -> None:
        self.warn("Session stopped early. Progress so far has been saved.")

    # ------------------------------------------------------------------ #
    # Daily summary
    # ------------------------------------------------------------------ #

    def render_summary(self, summary: DailySummary, streak_info: StreakInfo) -> None:
        self.rule(f"TODAY'S SUMMARY  ({summary.date})")

        table = Table.grid(padding=(0, 4))
        table.add_column()
        table.add_column()
        table.add_row(self._summary_table(summary), self._streak_table(streak_info))
        self.console.print(table)

        if summary.labels:
            self.rule("TIME BY TASK")
            t = Table(box=ROUNDED, border_style="bright_red", header_style="bold bright_red")
            t.add_column("Task")
            t.add_column("Minutes", justify="right")
            for name, mins in summary.labels:
                t.add_row(name, f"{mins:.1f}")
            self.console.print(t)

    def _summary_table(self, s: DailySummary) -> Table:
        t = Table(box=None, show_header=False, show_edge=False, pad_edge=False,
                  padding=(0, 1, 0, 0), title="Today", title_style="bold bright_red")
        t.add_column(style="dim bright_red", width=20)
        t.add_column(style="white")
        t.add_row("Focus minutes", f"{s.focus_minutes:.1f}")
        t.add_row("Work sessions", str(s.work_sessions))
        t.add_row("Completed", str(s.completed_sessions))
        t.add_row("Break minutes", f"{s.break_minutes:.1f}")
        return t

    def _streak_table(self, info: StreakInfo) -> Table:
        t = Table(box=None, show_header=False, show_edge=False, pad_edge=False,
                  padding=(0, 1, 0, 0), title="All-time", title_style="bold bright_red")
        t.add_column(style="dim bright_red", width=20)
        t.add_column(style="white")
        t.add_row("Current streak", f"{info.current_streak} day(s)")
        t.add_row("Longest streak", f"{info.longest_streak} day(s)")
        t.add_row("Active days", str(info.total_days_active))
        t.add_row("Total focus time", f"{info.total_focus_minutes / 60:.1f} hrs")
        return t

    # ------------------------------------------------------------------ #
    # Heatmap
    # ------------------------------------------------------------------ #

    def render_heatmap(self, grid: list[list[float]], start: date_cls, end: date_cls) -> None:
        self.rule(f"FOCUS HEATMAP  ({start:%b %d} – {end:%b %d})")

        cursor = start
        month_row = Text("     ")
        last_month = None
        for _ in grid:
            label = ""
            if cursor.day <= 7 and _MONTH_ABBR[cursor.month - 1] != last_month:
                label = _MONTH_ABBR[cursor.month - 1]
                last_month = label
            month_row.append(f"{label:<3}", style="dim white")
            cursor += timedelta(weeks=1)
        self.console.print(month_row)

        for day_index in range(7):
            row = Text(f"{_WEEKDAY_LABELS[day_index]:<5}", style="dim white")
            for week in grid:
                minutes = week[day_index]
                color = _heatmap_color(minutes)
                row.append("■ ", style=color)
            self.console.print(row)

        legend = Text("     less ")
        for _, color in _HEATMAP_LEVELS:
            legend.append("■ ", style=color)
        legend.append("more", style="dim white")
        self.console.print(legend)

    # ------------------------------------------------------------------ #
    # Week comparison
    # ------------------------------------------------------------------ #

    def render_week_comparison(self, c: WeekComparison) -> None:
        self.rule("THIS WEEK vs LAST WEEK")

        if c.trend == "no_data":
            self.console.print(Panel(
                Text("No sessions recorded for this week or last week yet.\n"
                     "Start a session to begin tracking your weekly trend.", style="yellow"),
                box=ROUNDED, border_style="yellow",
            ))
            return

        width = 28
        maximum = max(c.this_week_minutes, c.last_week_minutes, 1.0)
        body = Text()
        body.append("Focus minutes\n", style="bold white")
        body.append(f"  This week      ", style="bright_cyan")
        body.append(f"{bar(c.this_week_minutes, maximum, width):<{width}} ", style="bright_cyan")
        body.append(f"{c.this_week_minutes:g} min\n", style="bold bright_cyan")
        body.append(f"  Last week      ", style="bright_magenta")
        body.append(f"{bar(c.last_week_minutes, maximum, width):<{width}} ", style="bright_magenta")
        body.append(f"{c.last_week_minutes:g} min\n\n", style="bold bright_magenta")

        max_sessions = max(c.this_week_completed, c.last_week_completed, 1)
        body.append("Completed sessions\n", style="bold white")
        body.append(f"  This week      ", style="bright_cyan")
        body.append(f"{bar(c.this_week_completed, max_sessions, width):<{width}} ", style="bright_cyan")
        body.append(f"{c.this_week_completed}\n", style="bold bright_cyan")
        body.append(f"  Last week      ", style="bright_magenta")
        body.append(f"{bar(c.last_week_completed, max_sessions, width):<{width}} ", style="bright_magenta")
        body.append(f"{c.last_week_completed}\n", style="bold bright_magenta")

        self.console.print(Panel(body, box=ROUNDED, border_style="bright_red",
                                  title="[bold]SIDE-BY-SIDE[/bold]"))

        if c.trend == "new":
            self.console.print(Panel(
                Text("No sessions last week, so there's nothing to compare against yet - "
                     "this week's numbers are shown on their own.", style="yellow"),
                box=ROUNDED, border_style="yellow",
            ))
            return

        colour = "green" if c.trend == "up" else "red" if c.trend == "down" else "yellow"
        arrow = "▲" if c.trend == "up" else ("▼" if c.trend == "down" else "■")
        verdict = {
            "up": f"Focus time is up {abs(c.change_percent):.1f}% versus last week",
            "down": f"Focus time is down {abs(c.change_percent):.1f}% versus last week",
            "flat": "Focus time is about the same as last week",
        }[c.trend]
        self.console.print(Panel(
            Text(f"{arrow} {verdict}", style=f"bold {colour}"),
            box=ROUNDED, border_style=colour, title="[bold]VERDICT[/bold]",
        ))

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #

    def render_history(self, sessions: Sequence[SessionRecord]) -> None:
        self.rule("SESSION HISTORY")
        if not sessions:
            self.console.print("[dim]No sessions recorded yet. Start one from the main menu.[/dim]")
            return

        table = Table(box=ROUNDED, border_style="bright_red", header_style="bold bright_red")
        table.add_column("Date")
        table.add_column("Phase")
        table.add_column("Task")
        table.add_column("Planned", justify="right")
        table.add_column("Actual", justify="right")
        table.add_column("Status")
        for s in sessions:
            status = "[green]Completed[/green]" if s.completed else "[yellow]Cut short[/yellow]"
            phase_label = {"work": "🍅 Work", "short_break": "☕ Short break",
                          "long_break": "🌿 Long break"}.get(s.phase, s.phase)
            table.add_row(
                s.date, phase_label, s.label or "—",
                f"{s.planned_minutes} min", f"{s.actual_minutes:.1f} min", status,
            )
        self.console.print(table)

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #

    def render_settings(self, defaults) -> None:
        self.rule("CURRENT DEFAULTS")
        t = Table(box=None, show_header=False, show_edge=False, pad_edge=False)
        t.add_column(style="dim bright_red", width=24)
        t.add_column(style="white")
        t.add_row("Work session", f"{defaults.work_minutes} min")
        t.add_row("Short break", f"{defaults.short_break_minutes} min")
        t.add_row("Long break", f"{defaults.long_break_minutes} min")
        t.add_row("Cycles before long break", str(defaults.cycles_before_long_break))
        self.console.print(t)
