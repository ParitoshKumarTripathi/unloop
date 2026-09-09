"""Shared, deterministic support-goal routing.

Adapters declare a small vocabulary of domain-bounded goals.  The core owns the
lifecycle: user language selects or replaces the goal, parameters are extracted,
and the resulting subject set drives the existing stale fence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..tools.types import Subject


@dataclass(frozen=True)
class GoalDefinition:
    id: str
    label: str
    patterns: tuple[re.Pattern[str], ...]
    subjects: frozenset[Subject]
    tool_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SupportGoal:
    id: str
    label: str
    raw_utterance: str
    parameters: dict[str, Any] = field(default_factory=dict)
    subjects: frozenset[Subject] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "raw_utterance": self.raw_utterance,
            "parameters": dict(self.parameters),
            "subjects": sorted(subject.value for subject in self.subjects),
        }


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_GOAL_HINTS: dict[str, re.Pattern[str]] = {
    "resolve_otp": re.compile(r"(?:ओटीपी|वन.?टाइम|कोड)", re.IGNORECASE),
    "verify_card": re.compile(r"(?:कार्ड).*(?:स्थिति|ब्लॉक|चालू|पेमेंट)", re.IGNORECASE),
    "resolve_refund": re.compile(r"(?:रिफंड|पैसे वापस|क्रेडिट)", re.IGNORECASE),
    "cancel_order": re.compile(r"(?:ऑर्डर).*(?:रद्द|कैंसल)|(?:रद्द|कैंसल).*(?:ऑर्डर)", re.IGNORECASE),
    "return_order": re.compile(r"(?:रिटर्न|वापस भेज|गलत सामान|खराब सामान)", re.IGNORECASE),
    "change_party_size": re.compile(r"(?:लोग|व्यक्ति|मेहमान|पार्टी)", re.IGNORECASE),
    "cancel_reservation": re.compile(
        r"(?:रिजर्वेशन|बुकिंग).*(?:रद्द|कैंसल)|(?:रद्द|कैंसल).*(?:रिजर्वेशन|बुकिंग)", re.IGNORECASE
    ),
    "reschedule_reservation": re.compile(
        r"(?:समय बदल|पहले|बाद में|आगे|पीछे).*(?:रिजर्वेशन|बुकिंग)?", re.IGNORECASE
    ),
    "resolve_confirmation_mismatch": re.compile(r"(?:रेस्टोरेंट).*(?:नहीं मिल|गायब|गलत)", re.IGNORECASE),
    "cancel_appointment": re.compile(
        r"(?:अपॉइंटमेंट).*(?:रद्द|कैंसल)|(?:रद्द|कैंसल).*(?:अपॉइंटमेंट)", re.IGNORECASE
    ),
    "reschedule_appointment": re.compile(r"(?:अपॉइंटमेंट).*(?:समय बदल|पहले|बाद|आगे|पीछे)", re.IGNORECASE),
    "resolve_appointment_mismatch": re.compile(
        r"(?:अपॉइंटमेंट).*(?:नहीं मिल|गायब|गलत|बदल)", re.IGNORECASE
    ),
    "cancel_booking": re.compile(
        r"(?:होटल|बुकिंग).*(?:रद्द|कैंसल)|(?:रद्द|कैंसल).*(?:होटल|बुकिंग)", re.IGNORECASE
    ),
    "change_booking_dates": re.compile(r"(?:तारीख|चेक.?इन|चेक.?आउट).*(?:बदल|आगे|पीछे)", re.IGNORECASE),
    "resolve_booking_mismatch": re.compile(r"(?:होटल).*(?:नहीं मिल|गायब|गलत)", re.IGNORECASE),
}


def _extract_parameters(text: str) -> dict[str, Any]:
    """Extract common support-action slots without asking a model."""
    lowered = text.lower()
    params: dict[str, Any] = {}
    times = re.findall(
        r"\b(?:at|to|for|keep(?: it)? at)\s+(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))\b", lowered
    )
    if times:
        params["requested_time"] = times[-1].upper().replace(".", "")
    dates = re.findall(r"\b(?:to|from|on)\s+(\d{4}-\d{2}-\d{2})\b", lowered)
    if dates:
        params["requested_date"] = dates[-1]
    numbers = [int(value) for value in re.findall(r"\b\d+\b", lowered)]
    word_numbers = [
        _NUMBER_WORDS[word]
        for word in re.findall(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b", lowered)
    ]
    if re.search(r"\b(?:people|persons?|guests?|party size|party)\b", lowered):
        values = numbers + word_numbers
        if values:
            params["party_size"] = values[-1]
    if re.search(r"\b(?:room|rooms)\b", lowered) and numbers:
        params["room_count"] = numbers[-1]
    return params


class GoalRouter:
    """Choose the best adapter-declared goal from each final user utterance."""

    def __init__(self, definitions: tuple[GoalDefinition, ...]) -> None:
        self.definitions = definitions

    def detect(self, transcript: str) -> SupportGoal | None:
        best: tuple[int, int, GoalDefinition] | None = None
        for index, definition in enumerate(self.definitions):
            score = sum(1 for pattern in definition.patterns if pattern.search(transcript))
            hint = _GOAL_HINTS.get(definition.id)
            if hint and hint.search(transcript):
                score += 1
            candidate = (score, -index, definition)
            if score and (best is None or candidate[:2] > best[:2]):
                best = candidate
        if best is None:
            return None
        definition = best[2]
        return SupportGoal(
            id=definition.id,
            label=definition.label,
            raw_utterance=transcript,
            parameters=_extract_parameters(transcript),
            subjects=definition.subjects,
        )
