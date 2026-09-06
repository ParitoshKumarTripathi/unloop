"""Structured event log for UNLOOP.

Every meaningful thing the resolution engine does emits an event. The event log is
the evidence trail: acceptance tests assert against it, the debug UI renders it, and
``artifacts/events/*.jsonl`` is written from it.

Rules that hold everywhere in this module:

* Events are append-only. Nothing rewrites history.
* Every event carries ``timestamp``, ``session_id``, ``state_version``, ``event_type``.
* Metadata is non-sensitive by construction. There is no PII in the fixtures, and
  :func:`redact` strips anything that looks like a credential or a phone number
  before it is written, so a leak needs two independent mistakes.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class EventType(str, Enum):
    """The closed vocabulary of UNLOOP events.

    Kept as an enum rather than free strings so a typo in a test assertion is an
    ``AttributeError`` at import time instead of a silently passing test.
    """

    # --- call lifecycle -----------------------------------------------------
    CALL_STARTED = "CALL_STARTED"
    CALL_ENDED = "CALL_ENDED"

    # --- transcript ---------------------------------------------------------
    USER_TRANSCRIPT_INTERIM = "USER_TRANSCRIPT_INTERIM"
    USER_TRANSCRIPT_FINAL = "USER_TRANSCRIPT_FINAL"

    # --- resolution state ---------------------------------------------------
    STATE_VERSION_CHANGED = "STATE_VERSION_CHANGED"
    FACT_CONFIRMED = "FACT_CONFIRMED"
    HYPOTHESIS_CREATED = "HYPOTHESIS_CREATED"
    HYPOTHESIS_SUPPORTED = "HYPOTHESIS_SUPPORTED"
    HYPOTHESIS_REJECTED = "HYPOTHESIS_REJECTED"
    HYPOTHESIS_RESOLVED = "HYPOTHESIS_RESOLVED"
    HYPOTHESIS_REACTIVATED = "HYPOTHESIS_REACTIVATED"
    USER_CORRECTION = "USER_CORRECTION"
    STRATEGY_CHANGED = "STRATEGY_CHANGED"

    # --- tools --------------------------------------------------------------
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"
    TOOL_MARKED_STALE = "TOOL_MARKED_STALE"
    TOOL_RESULT_FENCED = "TOOL_RESULT_FENCED"

    # --- loop detection -----------------------------------------------------
    LOOP_SIGNAL = "LOOP_SIGNAL"
    LOOP_DETECTED = "LOOP_DETECTED"

    # --- speech lifecycle ---------------------------------------------------
    SPEECH_PROPOSED = "SPEECH_PROPOSED"
    OUTPUT_GUARD_REJECTION = "OUTPUT_GUARD_REJECTION"
    SPEECH_FENCED_STALE = "SPEECH_FENCED_STALE"
    NEW_RESPONSE_STARTED = "NEW_RESPONSE_STARTED"
    RIME_REQUEST_STARTED = "RIME_REQUEST_STARTED"
    RIME_FIRST_AUDIO = "RIME_FIRST_AUDIO"
    AGENT_SPEECH_STARTED = "AGENT_SPEECH_STARTED"
    AGENT_SPEECH_COMPLETED = "AGENT_SPEECH_COMPLETED"
    AGENT_INTERRUPTED = "AGENT_INTERRUPTED"

    # --- barge-in instrumentation ------------------------------------------
    USER_SPEECH_START = "USER_SPEECH_START"
    INTERRUPTION_DETECTED = "INTERRUPTION_DETECTED"
    FALSE_INTERRUPTION = "FALSE_INTERRUPTION"
    AGENT_AUDIO_STOP_REQUESTED = "AGENT_AUDIO_STOP_REQUESTED"
    AGENT_AUDIO_STOPPED = "AGENT_AUDIO_STOPPED"

    # --- escalation ---------------------------------------------------------
    ESCALATION_CREATED = "ESCALATION_CREATED"

    # --- demo / harness controls -------------------------------------------
    MOCK_DELAY_SET = "MOCK_DELAY_SET"
    FIXTURE_LOADED = "FIXTURE_LOADED"

    # --- diagnostics --------------------------------------------------------
    ERROR = "ERROR"


# Patterns for values that must never reach the event log. The fixtures are wholly
# synthetic, so in normal operation none of these fire; they exist so that a future
# careless ``meta={"key": api_key}`` is caught by machinery rather than by review.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|password|authorization|bearer)\b"), "<redacted>"),
    (re.compile(r"\+?\d[\d\s\-()]{8,}\d"), "<number-redacted>"),
)


def redact(value: Any) -> Any:
    """Recursively scrub credential-shaped and phone-number-shaped values.

    Applied to keys as well as values: a key named ``api_key`` gets its *value*
    replaced regardless of what the value looks like.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _REDACTIONS[0][0].search(str(k)):
                out[str(k)] = "<redacted>"
            else:
                out[str(k)] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        scrubbed = value
        for pattern, replacement in _REDACTIONS:
            scrubbed = pattern.sub(replacement, scrubbed)
        return scrubbed
    return value


@dataclass(frozen=True)
class Event:
    """One immutable entry in the resolution timeline."""

    event_type: EventType
    session_id: str
    state_version: int
    timestamp: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)
    #: Monotonic sequence number, assigned by the recorder. Wall-clock timestamps can
    #: tie at millisecond resolution; ordering assertions use this instead.
    seq: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "session_id": self.session_id,
            "state_version": self.state_version,
            "meta": self.meta,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), default=str)


class EventRecorder:
    """Append-only, thread-safe event sink.

    Thread-safety matters: tool callbacks can complete on a worker thread while the
    session loop is emitting speech events, and the acceptance tests assert on
    ordering. A dropped or reordered event would be an invisible test failure.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._subscribers: list[Callable[[Event], None]] = []

    def emit(
        self,
        event_type: EventType,
        *,
        state_version: int,
        **meta: Any,
    ) -> Event:
        """Record an event and notify subscribers.

        A failing subscriber must never break the engine, so subscriber exceptions
        are swallowed after the event is safely stored.
        """
        with self._lock:
            self._seq += 1
            event = Event(
                event_type=event_type,
                session_id=self.session_id,
                state_version=state_version,
                meta=redact(meta),
                seq=self._seq,
            )
            self._events.append(event)
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:  # noqa: BLE001 - observability must not break the call
                pass
        return event

    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        """Register a live listener (the debug UI bridge). Returns an unsubscribe fn."""
        with self._lock:
            self._subscribers.append(callback)

        def _unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return _unsubscribe

    # --- reading ------------------------------------------------------------

    @property
    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def of_type(self, *types: EventType) -> list[Event]:
        wanted = set(types)
        return [e for e in self.events if e.event_type in wanted]

    def after(self, event: Event) -> list[Event]:
        """Every event recorded strictly after ``event``.

        The acceptance suite's central assertion — "no spoken assertion of a rejected
        diagnosis appears *after* the rejection" — is expressed with this.
        """
        return [e for e in self.events if e.seq > event.seq]

    def first(self, event_type: EventType) -> Event | None:
        for event in self.events:
            if event.event_type is event_type:
                return event
        return None

    def last(self, event_type: EventType) -> Event | None:
        for event in reversed(self.events):
            if event.event_type is event_type:
                return event
        return None

    # --- writing ------------------------------------------------------------

    def write_jsonl(self, path: str | Path) -> Path:
        """Persist the raw timeline. Raw data is kept, never summarised away."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(event.to_json() + "\n")
        return target
