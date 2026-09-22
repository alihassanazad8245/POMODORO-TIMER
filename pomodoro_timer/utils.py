"""Small formatting helpers shared by the UI layer."""

from __future__ import annotations

_BLOCKS = " ▏▎▍▌▋▊▉█"


def bar(value: float, maximum: float, width: int = 24) -> str:
    """Build a smooth Unicode bar using eighth-block characters."""
    if maximum <= 0 or value <= 0:
        return ""
    exact = max(0.0, min(float(width), value / maximum * width))
    full = int(exact)
    remainder = exact - full
    partial = _BLOCKS[int(remainder * 8)] if full < width else ""
    rendered = ("█" * full) + partial
    return rendered if rendered.strip() else "▏"
