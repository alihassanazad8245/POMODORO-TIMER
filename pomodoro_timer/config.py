"""Centralised configuration.

Everything the timer needs lives under ``data/`` in the project root:
``sessions.json`` (the session log) and ``config.json`` (persisted default
durations, written only when the user explicitly saves new defaults). Nothing
is written outside the project folder, and nothing ever requires a token.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SESSIONS_FILE = DATA_DIR / "sessions.json"
CONFIG_FILE = DATA_DIR / "config.json"

# Standard Pomodoro Technique defaults.
DEFAULT_WORK_MINUTES = 25
DEFAULT_SHORT_BREAK_MINUTES = 5
DEFAULT_LONG_BREAK_MINUTES = 15
DEFAULT_CYCLES_BEFORE_LONG_BREAK = 4

DEFAULT_HEATMAP_WEEKS = 12
DEFAULT_HISTORY_LIMIT = 15

#: Hard bounds so a mistyped flag can't create a 0-second or multi-day timer.
MIN_MINUTES = 1
MAX_MINUTES = 180

#: App identifier used for the Windows toast notification.
NOTIFIER_APP_ID = "Pomodoro Timer"


@dataclass(slots=True)
class TimerDefaults:
    """Durations and cycle count, either built-in or loaded from config.json."""

    work_minutes: int = DEFAULT_WORK_MINUTES
    short_break_minutes: int = DEFAULT_SHORT_BREAK_MINUTES
    long_break_minutes: int = DEFAULT_LONG_BREAK_MINUTES
    cycles_before_long_break: int = DEFAULT_CYCLES_BEFORE_LONG_BREAK

    def to_dict(self) -> dict[str, int]:
        return {
            "work_minutes": self.work_minutes,
            "short_break_minutes": self.short_break_minutes,
            "long_break_minutes": self.long_break_minutes,
            "cycles_before_long_break": self.cycles_before_long_break,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimerDefaults":
        defaults = cls()
        for field_name in ("work_minutes", "short_break_minutes",
                           "long_break_minutes", "cycles_before_long_break"):
            value = data.get(field_name)
            if isinstance(value, int) and value > 0:
                setattr(defaults, field_name, value)
        return defaults


@dataclass(slots=True)
class Settings:
    """Runtime settings for a single CLI invocation."""

    no_color: bool = False
    verbose: bool = False
    data_dir: Path = DATA_DIR
