"""The stale fence — UNLOOP's central invariant.

A voice agent is a distributed system with a human in it. A tool call issued three
seconds ago answers a question the caller may have already withdrawn; a response the
LLM started generating before the caller interrupted is a reply to a sentence that no
longer exists. Both will happily arrive, look valid, and get spoken.

This module is the single place that decides whether a late arrival may still speak.
It is application-level and deterministic. It is *not* a line in a system prompt
saying "ignore stale results" — a prompt is a request, and the acceptance criterion
for this behaviour is zero failures in twenty runs.

Two things pass through the fence:

* **tool results** — :meth:`StaleFence.evaluate_tool`
* **proposed speech** — :meth:`StaleFence.authorize_speech`

Both compare the version they were born under against the current state version, and
consult the version log to find out *what* changed in between. That last part matters:
discarding every late result would be simple and wrong, because most late results are
still perfectly good. Only results whose subject a caller correction actually
invalidated are superseded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..observability.events import EventType
from ..tools.types import Subject, ToolResult
from .state import ResolutionState


class FenceVerdict(str, Enum):
    """What the fence decided about a late arrival."""

    FRESH = "FRESH"
    """Born under the current state version. Fully usable."""

    RECONCILABLE = "RECONCILABLE"
    """The state moved on, but nothing that happened in between touched this
    subject. The result is still true and may inform state and speech — an OTP
    delivery check does not become wrong because the caller corrected us about the
    card."""

    SUPERSEDED = "SUPERSEDED"
    """A correction between issue and arrival invalidated this subject. The result
    is marked stale, kept as historical evidence, and **may not produce speech**."""


@dataclass(frozen=True)
class FenceDecision:
    verdict: FenceVerdict
    reason: str
    originating_version: int
    current_version: int
    invalidated_subjects: frozenset[Subject] = field(default_factory=frozenset)

    @property
    def may_speak(self) -> bool:
        return self.verdict is not FenceVerdict.SUPERSEDED

    @property
    def is_stale(self) -> bool:
        return self.verdict is FenceVerdict.SUPERSEDED


@dataclass(frozen=True)
class SpeechTicket:
    """A proposed spoken turn, tagged with the state it was generated under.

    Created at generation time, checked immediately before the text is handed to
    Rime. Preemptive generation is on (ADR-007), so the gap between those two moments
    is exactly where obsolete replies are born.
    """

    speech_id: str
    state_version: int
    text: str
    intent: str = ""
    #: Hypotheses this turn asserts, as determined by the output guard's matcher.
    asserted_hypotheses: tuple[str, ...] = ()
    #: Subjects this turn's content depends on. If a correction invalidated one of
    #: them after generation, the turn is obsolete regardless of its wording.
    depends_on: frozenset[Subject] = field(default_factory=frozenset)


@dataclass(frozen=True)
class SpeechDecision:
    allowed: bool
    reason: str
    blocking_rule: str | None = None
    blocked_hypotheses: tuple[str, ...] = ()


class StaleFence:
    """Version-aware gate for tool results and outgoing speech."""

    def __init__(self, state: ResolutionState) -> None:
        self._state = state

    # -- tool results --------------------------------------------------------

    def evaluate_tool(self, result: ToolResult) -> FenceDecision:
        """Classify a returning tool result against the current state.

        Mutates ``result.stale`` and ``result.fence_verdict`` so the decision travels
        with the result and can be asserted on afterwards. Emits ``TOOL_MARKED_STALE``
        for a superseded result and ``TOOL_RESULT_FENCED`` for every evaluation, so
        the timeline shows the fence doing its job even when it lets something pass.
        """
        state = self._state
        current = state.state_version
        origin = result.state_version

        if origin == current:
            decision = FenceDecision(
                verdict=FenceVerdict.FRESH,
                reason="issued under the current state version",
                originating_version=origin,
                current_version=current,
            )
        else:
            invalidated = state.subjects_invalidated_since(origin)
            if result.subject in invalidated:
                decision = FenceDecision(
                    verdict=FenceVerdict.SUPERSEDED,
                    reason=(
                        f"a correction after v{origin} invalidated subject "
                        f"{result.subject.value!r}"
                    ),
                    originating_version=origin,
                    current_version=current,
                    invalidated_subjects=frozenset(invalidated),
                )
            else:
                decision = FenceDecision(
                    verdict=FenceVerdict.RECONCILABLE,
                    reason=(
                        f"state advanced v{origin}->v{current} but nothing invalidated "
                        f"subject {result.subject.value!r}"
                    ),
                    originating_version=origin,
                    current_version=current,
                    invalidated_subjects=frozenset(invalidated),
                )

        result.stale = decision.is_stale
        result.fence_verdict = decision.verdict.value

        if decision.is_stale:
            state.recorder.emit(
                EventType.TOOL_MARKED_STALE,
                state_version=current,
                tool_call_id=result.tool_call_id,
                tool_name=result.tool_name,
                subject=result.subject.value,
                originating_state_version=origin,
                current_state_version=current,
                reason=decision.reason,
            )

        state.recorder.emit(
            EventType.TOOL_RESULT_FENCED,
            state_version=current,
            tool_call_id=result.tool_call_id,
            tool_name=result.tool_name,
            verdict=decision.verdict.value,
            may_speak=decision.may_speak,
            originating_state_version=origin,
            current_state_version=current,
            reason=decision.reason,
        )
        return decision

    # -- speech --------------------------------------------------------------

    def authorize_speech(self, ticket: SpeechTicket) -> SpeechDecision:
        """Decide whether a proposed turn may still be spoken.

        Three rules, applied in order. The first is the contradicted-diagnosis rule
        and it applies at *any* version, including the current one: an LLM can produce
        a rejected diagnosis in a brand-new response just as easily as in a stale one.
        """
        state = self._state

        # Rule 1 — never assert a hypothesis the caller has refuted.
        blocked = tuple(
            hid
            for hid in ticket.asserted_hypotheses
            if (h := state.get_hypothesis(hid)) is not None and h.is_rejected
        )
        if blocked:
            state.recorder.emit(
                EventType.OUTPUT_GUARD_REJECTION,
                state_version=state.state_version,
                speech_id=ticket.speech_id,
                blocked_hypotheses=list(blocked),
                ticket_state_version=ticket.state_version,
                text_preview=ticket.text[:160],
            )
            return SpeechDecision(
                allowed=False,
                reason=f"asserts rejected hypothesis: {', '.join(blocked)}",
                blocking_rule="REJECTED_HYPOTHESIS",
                blocked_hypotheses=blocked,
            )

        # Rule 2 — a turn generated before a correction that invalidated its subject
        # is answering a question the caller has withdrawn.
        if ticket.state_version < state.state_version:
            invalidated = state.subjects_invalidated_since(ticket.state_version)
            overlap = invalidated & set(ticket.depends_on)
            if overlap:
                state.recorder.emit(
                    EventType.SPEECH_FENCED_STALE,
                    state_version=state.state_version,
                    speech_id=ticket.speech_id,
                    ticket_state_version=ticket.state_version,
                    current_state_version=state.state_version,
                    invalidated_subjects=sorted(s.value for s in overlap),
                    text_preview=ticket.text[:160],
                )
                return SpeechDecision(
                    allowed=False,
                    reason=(
                        f"generated at v{ticket.state_version}; correction invalidated "
                        f"{', '.join(sorted(s.value for s in overlap))}"
                    ),
                    blocking_rule="SUPERSEDED_SPEECH",
                )

        # Rule 3 — otherwise allow. A turn that merely drifted in version but whose
        # content nothing contradicted is still correct, and blocking it would make
        # the agent needlessly mute after every correction.
        return SpeechDecision(allowed=True, reason="no rejected assertion, no invalidated dependency")

    # -- helpers -------------------------------------------------------------

    def is_speech_current(self, ticket: SpeechTicket) -> bool:
        return ticket.state_version == self._state.state_version
