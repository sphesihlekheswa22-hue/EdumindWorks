"""Shared helpers for score/percentage calculations (always 0–100)."""
from __future__ import annotations


def clamp_pct(value) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, number))


def percentage_from_parts(score, total, *, decimals: int = 2) -> float:
    """Convert score/total to a percentage capped at 0–100."""
    try:
        earned = float(score or 0)
        possible = float(total or 0)
    except (TypeError, ValueError):
        return 0.0
    if possible <= 0:
        return 0.0
    raw = (earned / possible) * 100
    return round(clamp_pct(raw), decimals)


def format_pct(value, decimals: int = 0) -> str:
    number = clamp_pct(value)
    if decimals <= 0:
        return str(int(round(number)))
    return f"{number:.{decimals}f}"
