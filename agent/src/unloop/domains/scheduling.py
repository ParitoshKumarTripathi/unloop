"""Shared normalization for date/time corrective actions across support domains."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

_COMBINED_DATETIME = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})[T\s]+(?P<time>\d{1,2}(?::\d{2})?\s*(?:AM|PM))\s*$",
    re.IGNORECASE,
)


def normalise_date(value: object, *, field: str = "date") -> str:
    raw = str(value or "").strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc


def normalise_time(value: object) -> str:
    raw = str(value or "").strip().upper().replace(".", "")
    for pattern in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            parsed = datetime.strptime(raw, pattern)
            return parsed.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue
    raise ValueError("time must contain only a clock time such as 6:00 PM")


def target_schedule(
    current: dict[str, Any], *, requested_date: object = None, requested_time: object = None
) -> tuple[str, str]:
    """Canonicalize a date/time pair, including defensively splitting a combined value."""
    date_value = str(requested_date or "").strip()
    time_value = str(requested_time or "").strip()
    combined = _COMBINED_DATETIME.fullmatch(time_value)
    if combined:
        embedded_date = combined.group("date")
        if date_value and date_value != embedded_date:
            raise ValueError("conflicting dates were supplied")
        date_value = embedded_date
        time_value = combined.group("time")

    return (
        normalise_date(date_value or current["date"]),
        normalise_time(time_value or current["time"]),
    )


def target_date_range(
    current: dict[str, Any], *, check_in: object = None, check_out: object = None
) -> tuple[str, str]:
    start = normalise_date(check_in or current["check_in"], field="check_in")
    end = normalise_date(check_out or current["check_out"], field="check_out")
    if end <= start:
        raise ValueError("hotel check-out must be after check-in")
    return start, end


def bounded_count(value: object, *, field: str, maximum: int = 20) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a whole number")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a whole number") from exc
    if str(value).strip() != str(count) and not isinstance(value, int):
        raise ValueError(f"{field} must be a whole number")
    if not 1 <= count <= maximum:
        raise ValueError(f"{field} must be between 1 and {maximum}")
    return count


def concise_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 80 or any(char in text for char in "\r\n"):
        raise ValueError(f"invalid {field} value")
    return text
