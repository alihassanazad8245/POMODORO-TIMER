"""Local JSON storage for the session log and persisted defaults.

No database, no external service. Writes are atomic (write to a temp file,
then replace) so a crash mid-write can never corrupt the real log file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import CONFIG_FILE, DATA_DIR, SESSIONS_FILE, TimerDefaults
from .errors import StorageError
from .models import SessionRecord


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (safe against crashes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    except OSError as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise StorageError(f"Could not write to '{path}'.") from exc


def load_sessions(path: Path | None = None) -> list[SessionRecord]:
    """Load every recorded session. A missing or corrupted file yields []."""
    path = path if path is not None else SESSIONS_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [SessionRecord.from_dict(item) for item in raw if isinstance(item, dict)]


def append_session(record: SessionRecord, path: Path | None = None) -> None:
    """Append one session record to the log."""
    path = path if path is not None else SESSIONS_FILE
    sessions = load_sessions(path)
    sessions.append(record)
    _atomic_write(path, json.dumps([s.to_dict() for s in sessions], indent=2))


def load_config(path: Path | None = None) -> TimerDefaults:
    """Load persisted timer defaults, or the built-in defaults if none saved."""
    path = path if path is not None else CONFIG_FILE
    if not path.exists():
        return TimerDefaults()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TimerDefaults()
    if not isinstance(raw, dict):
        return TimerDefaults()
    return TimerDefaults.from_dict(raw)


def save_config(defaults: TimerDefaults, path: Path | None = None) -> None:
    """Persist timer defaults for future sessions."""
    path = path if path is not None else CONFIG_FILE
    _atomic_write(path, json.dumps(defaults.to_dict(), indent=2))


def ensure_data_dir(data_dir: Path | None = None) -> None:
    """Create the data directory if it doesn't exist yet."""
    data_dir = data_dir if data_dir is not None else DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
