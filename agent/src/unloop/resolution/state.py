"""``ResolutionState`` — the authoritative record of the call.

This object, not the LLM's context window, is what UNLOOP believes. The model can
propose; only this object decides. Everything here is plain Python and pure logic, so
the invariants that matter can be tested with no key, no socket and no model.

The central mechanic is ``state_version``. It increments on every meaningful user
correction, and every asynchronous thing in flight — tool calls, generated responses,
queued speech — remembers the version it was born under. Comparing those two numbers
is how UNLOOP knows that a result which just arrived is answering a question the
caller has already moved on from.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..observability.events import EventRecorder, EventType
from ..tools.types import HeardStatus, PendingToolCall, Subject, ToolResult
from .hypotheses import Evidence, EvidenceSource, Hypothesis, HypothesisStatus


class EscalationStatus(str, Enum):
    NONE = "NONE"
    RECOMMENDED = "RECOMMENDED"
    CREATED = "CREATED"
    HANDED_OFF = "HANDED_OFF"


@dataclass
class Fact:
    """Something UNLOOP has established and is willing to say out loud."""

    key: str
    value: str
    source: EvidenceSource
    state_version: int
    detail: dict[str, Any] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source.value,
            "state_version": self.state_version,
            "detail": self.detail,
        }


@dataclass
class Correction:
    """A caller statement that contradicts what the agent was assuming.

    ``invalidates`` is the load-bearing field. It names the *subjects* this correction
    makes obsolete, which is what the stale fence consults when a late tool result
    turns up.
    """

    id: str
    target_hypothesis: str | None
    claim: str
    evidence: str
    invalidates: set[Subject]
    state_version_before: int
    state_version_after: int
    raw_utterance: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_hypothesis": self.target_hypothesis,
            "claim": self.claim,
            "evidence": self.evidence,
            "invalidates": sorted(s.value for s in self.invalidates),
            "state_version_before": self.state_version_before,
            "state_version_after": self.state_version_after,
        }


@dataclass
class VersionBump:
    """One increment of ``state_version``, with the reason it happened.

    The fence walks this log to decide whether a late arrival is merely *old* or
    genuinely *superseded* — a distinction that matters, because discarding every
    late result would throw away evidence we paid for.
    """

    from_version: int
    to_version: int
    reason: str
    correction_id: str | None = None
    invalidated_subjects: set[Subject] = field(default_factory=set)
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "reason": self.reason,
            "correction_id": self.correction_id,
            "invalidated_subjects": sorted(s.value for s in self.invalidated_subjects),
        }


@dataclass
class SpeechRecord:
    """The lifecycle of one spoken agent turn.

    ``heard_status`` is an honest field. ``COMPLETED`` means LiveKit reported the
    playout finished; ``INTERRUPTED`` means it was cut and ``heard_text`` holds the
    SDK's synchronized transcript of what was actually audible. Where that transcript
    came from Rime's word timestamps rather than an estimated speaking rate,
    ``aligned`` is True — see ADR-006 and the limitations section of RIME_EVIDENCE.md.
    """

    speech_id: str
    state_version: int
    text: str
    intent: str = ""
    asserted_hypotheses: list[str] = field(default_factory=list)
    started_at: float | None = None
    completed_at: float | None = None
    interrupted_at: float | None = None
    heard_status: HeardStatus = "NOT_STARTED"
    heard_text: str = ""
    aligned: bool = False

    @property
    def was_heard(self) -> bool:
        """Whether the caller actually received this content.

        A turn that was generated but never played does not count as communicated.
        A turn cut off after one word counts only for the words in ``heard_text``.
        """
        return self.heard_status in ("COMPLETED", "PARTIAL") and bool(self.heard_text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "speech_id": self.speech_id,
            "state_version": self.state_version,
            "text": self.text,
            "intent": self.intent,
            "asserted_hypotheses": self.asserted_hypotheses,
            "heard_status": self.heard_status,
            "heard_text": self.heard_text,
            "aligned": self.aligned,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "interrupted_at": self.interrupted_at,
        }


class ResolutionState:
    """Authoritative, deterministic state for one support call."""

    def __init__(
        self,
        *,
        session_id: str | None = None,
        recorder: EventRecorder | None = None,
        issue_type: str = "UNKNOWN",
        issue_summary: str = "",
        hypotheses: list[Hypothesis] | None = None,
    ) -> None:
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.case_id: str | None = None
        self.state_version: int = 1
        self.turn: int = 0

        self.issue_type = issue_type
        self.issue_summary = issue_summary

        self.confirmed_facts: list[Fact] = []
        self.user_corrections: list[Correction] = []
        self.hypotheses: dict[str, Hypothesis] = {h.id: h for h in (hypotheses or [])}
        self.attempted_actions: list[str] = []
        self.pending_tools: dict[str, PendingToolCall] = {}
        self.completed_tools: list[ToolResult] = []
        self.version_log: list[VersionBump] = []

        self.current_strategy: str = "triage"
        self.loop_score: int = 0
        self.escalation_status: EscalationStatus = EscalationStatus.NONE
        self.escalation_reason: str | None = None

        self.last_agent_intent: str = ""
        self.last_user_intent: str = ""

        self.speech_records: dict[str, SpeechRecord] = {}

        self.recorder = recorder or EventRecorder(self.session_id)

    # --- versioning ---------------------------------------------------------

    def bump_version(
        self,
        reason: str,
        *,
        correction_id: str | None = None,
        invalidates: set[Subject] | None = None,
    ) -> int:
        """Advance the state version. The one operation that can make things stale."""
        previous = self.state_version
        self.state_version += 1
        bump = VersionBump(
            from_version=previous,
            to_version=self.state_version,
            reason=reason,
            correction_id=correction_id,
            invalidated_subjects=set(invalidates or set()),
        )
        self.version_log.append(bump)
        self.recorder.emit(
            EventType.STATE_VERSION_CHANGED,
            state_version=self.state_version,
            from_version=previous,
            to_version=self.state_version,
            reason=reason,
            correction_id=correction_id,
            invalidated_subjects=sorted(s.value for s in bump.invalidated_subjects),
        )
        return self.state_version

    def subjects_invalidated_since(self, version: int) -> set[Subject]:
        """Every subject invalidated by a bump that happened after ``version``.

        A tool issued at version *v* is superseded if its subject appears here for
        ``version=v``. This is the whole of the staleness rule.
        """
        invalidated: set[Subject] = set()
        for bump in self.version_log:
            if bump.to_version > version:
                invalidated |= bump.invalidated_subjects
        return invalidated

    # --- facts --------------------------------------------------------------

    def confirm_fact(
        self,
        key: str,
        value: str,
        *,
        source: EvidenceSource = EvidenceSource.TOOL,
        detail: dict[str, Any] | None = None,
    ) -> Fact:
        fact = Fact(
            key=key,
            value=value,
            source=source,
            state_version=self.state_version,
            detail=detail or {},
        )
        self.confirmed_facts.append(fact)
        self.recorder.emit(
            EventType.FACT_CONFIRMED,
            state_version=self.state_version,
            key=key,
            value=value,
            source=source.value,
        )
        return fact

    def fact(self, key: str) -> Fact | None:
        for candidate in reversed(self.confirmed_facts):
            if candidate.key == key:
                return candidate
        return None

    # --- hypotheses ---------------------------------------------------------

    def add_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        hypothesis.first_seen_turn = self.turn
        self.hypotheses[hypothesis.id] = hypothesis
        self.recorder.emit(
            EventType.HYPOTHESIS_CREATED,
            state_version=self.state_version,
            hypothesis_id=hypothesis.id,
            label=hypothesis.label,
            branch=hypothesis.branch,
        )
        return hypothesis

    def get_hypothesis(self, hypothesis_id: str) -> Hypothesis | None:
        return self.hypotheses.get(hypothesis_id)

    @property
    def rejected_hypotheses(self) -> list[Hypothesis]:
        return [h for h in self.hypotheses.values() if h.status is HypothesisStatus.REJECTED]

    @property
    def active_hypotheses(self) -> list[Hypothesis]:
        return [
            h
            for h in self.hypotheses.values()
            if h.status in (HypothesisStatus.ACTIVE, HypothesisStatus.SUPPORTED)
        ]

    def support_hypothesis(self, hypothesis_id: str, evidence: Evidence) -> Hypothesis | None:
        hypothesis = self.hypotheses.get(hypothesis_id)
        if hypothesis is None:
            return None
        was_rejected = hypothesis.is_rejected
        hypothesis.add_support(evidence, turn=self.turn)
        if was_rejected:
            # Recorded but not acted on: add_support() deliberately refuses to lift a
            # rejection. Surfacing the tension is useful; silently undoing it is not.
            self.recorder.emit(
                EventType.LOOP_SIGNAL,
                state_version=self.state_version,
                signal="support_for_rejected_hypothesis",
                hypothesis_id=hypothesis_id,
                evidence_id=evidence.id,
            )
        else:
            self.recorder.emit(
                EventType.HYPOTHESIS_SUPPORTED,
                state_version=self.state_version,
                hypothesis_id=hypothesis_id,
                evidence_id=evidence.id,
                confidence=round(hypothesis.confidence, 3),
            )
        return hypothesis

    def reject_hypothesis(self, hypothesis_id: str, evidence: Evidence) -> Hypothesis | None:
        hypothesis = self.hypotheses.get(hypothesis_id)
        if hypothesis is None:
            return None
        hypothesis.reject(evidence, turn=self.turn, state_version=self.state_version)
        self.recorder.emit(
            EventType.HYPOTHESIS_REJECTED,
            state_version=self.state_version,
            hypothesis_id=hypothesis_id,
            label=hypothesis.label,
            evidence_id=evidence.id,
            evidence_source=evidence.source.value,
            evidence_summary=evidence.summary,
        )
        return hypothesis

    def reactivate_hypothesis(self, hypothesis_id: str, evidence: Evidence) -> Hypothesis | None:
        hypothesis = self.hypotheses.get(hypothesis_id)
        if hypothesis is None or not hypothesis.can_reactivate(evidence):
            return None
        hypothesis.reactivate(evidence, turn=self.turn)
        self.recorder.emit(
            EventType.HYPOTHESIS_REACTIVATED,
            state_version=self.state_version,
            hypothesis_id=hypothesis_id,
            evidence_id=evidence.id,
            evidence_summary=evidence.summary,
        )
        return hypothesis

    # --- corrections --------------------------------------------------------

    def record_correction(
        self,
        *,
        target_hypothesis: str | None,
        claim: str,
        evidence: str,
        invalidates: set[Subject],
        raw_utterance: str = "",
    ) -> Correction:
        """Register a caller correction and advance the state version.

        Order matters here: the correction is constructed with the version *before*
        the bump, then the bump records the correction id. That way the version log
        and the correction list agree about which version boundary belongs to which
        caller statement.
        """
        correction_id = f"corr_{len(self.user_corrections) + 1}"
        before = self.state_version
        after = self.bump_version(
            f"user correction: {claim}",
            correction_id=correction_id,
            invalidates=invalidates,
        )
        correction = Correction(
            id=correction_id,
            target_hypothesis=target_hypothesis,
            claim=claim,
            evidence=evidence,
            invalidates=set(invalidates),
            state_version_before=before,
            state_version_after=after,
            raw_utterance=raw_utterance,
        )
        self.user_corrections.append(correction)
        self.recorder.emit(
            EventType.USER_CORRECTION,
            state_version=self.state_version,
            correction_id=correction_id,
            target_hypothesis=target_hypothesis,
            claim=claim,
            evidence=evidence,
            invalidates=sorted(s.value for s in invalidates),
        )
        return correction

    # --- tools --------------------------------------------------------------

    def start_tool(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        subject: Subject,
        injected_delay_ms: int = 0,
    ) -> PendingToolCall:
        pending = PendingToolCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            subject=subject,
            state_version=self.state_version,
            injected_delay_ms=injected_delay_ms,
        )
        self.pending_tools[tool_call_id] = pending
        self.attempted_actions.append(tool_name)
        self.recorder.emit(
            EventType.TOOL_STARTED,
            state_version=self.state_version,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            subject=subject.value,
            injected_delay_ms=injected_delay_ms,
        )
        return pending

    def complete_tool(self, result: ToolResult) -> ToolResult:
        self.pending_tools.pop(result.tool_call_id, None)
        self.completed_tools.append(result)
        self.recorder.emit(
            EventType.TOOL_COMPLETED if result.succeeded else EventType.TOOL_FAILED,
            state_version=self.state_version,
            tool_call_id=result.tool_call_id,
            tool_name=result.tool_name,
            subject=result.subject.value,
            originating_state_version=result.state_version,
            status=result.status.value,
            duration_ms=round(result.duration_ms or 0.0, 1),
            payload=result.payload,
            error=result.error,
        )
        return result

    def tool_result(self, tool_call_id: str) -> ToolResult | None:
        for result in self.completed_tools:
            if result.tool_call_id == tool_call_id:
                return result
        return None

    def latest_result_for(self, subject: Subject) -> ToolResult | None:
        """Most recent non-stale result about a subject."""
        for result in reversed(self.completed_tools):
            if result.subject is subject and not result.stale and result.succeeded:
                return result
        return None

    # --- speech -------------------------------------------------------------

    def register_speech(self, record: SpeechRecord) -> SpeechRecord:
        self.speech_records[record.speech_id] = record
        return record

    @property
    def heard_agent_turns(self) -> list[SpeechRecord]:
        return [r for r in self.speech_records.values() if r.was_heard]

    @property
    def interrupted_agent_turns(self) -> list[SpeechRecord]:
        return [r for r in self.speech_records.values() if r.heard_status == "INTERRUPTED"]

    def mark_hypothesis_suggested(self, hypothesis_id: str) -> None:
        """Count a suggestion only once it was actually audible.

        Called from the speech-completion path, not the generation path — a diagnosis
        the caller never heard has not been suggested to them, and counting it would
        make the loop detector fire on turns that never happened.
        """
        hypothesis = self.hypotheses.get(hypothesis_id)
        if hypothesis is not None:
            hypothesis.times_suggested_to_user += 1

    # --- strategy / escalation ---------------------------------------------

    def set_strategy(self, strategy: str, *, reason: str = "") -> None:
        if strategy == self.current_strategy:
            return
        previous = self.current_strategy
        self.current_strategy = strategy
        self.recorder.emit(
            EventType.STRATEGY_CHANGED,
            state_version=self.state_version,
            from_strategy=previous,
            to_strategy=strategy,
            reason=reason,
        )

    def set_escalation(self, status: EscalationStatus, *, reason: str) -> None:
        self.escalation_status = status
        self.escalation_reason = reason

    # --- serialisation ------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """A JSON-safe view of the whole state — what the debug panel renders."""
        return {
            "session_id": self.session_id,
            "case_id": self.case_id,
            "state_version": self.state_version,
            "turn": self.turn,
            "issue_type": self.issue_type,
            "issue_summary": self.issue_summary,
            "current_strategy": self.current_strategy,
            "loop_score": self.loop_score,
            "escalation_status": self.escalation_status.value,
            "escalation_reason": self.escalation_reason,
            "last_agent_intent": self.last_agent_intent,
            "last_user_intent": self.last_user_intent,
            "confirmed_facts": [f.to_dict() for f in self.confirmed_facts],
            "user_corrections": [c.to_dict() for c in self.user_corrections],
            "hypotheses": [h.to_dict() for h in self.hypotheses.values()],
            "rejected_hypotheses": [h.id for h in self.rejected_hypotheses],
            "attempted_actions": list(self.attempted_actions),
            "pending_tools": [p.model_dump(mode="json") for p in self.pending_tools.values()],
            "completed_tools": [t.model_dump(mode="json") for t in self.completed_tools],
            "stale_tool_count": sum(1 for t in self.completed_tools if t.stale),
            "version_log": [v.to_dict() for v in self.version_log],
            "speech_records": [s.to_dict() for s in self.speech_records.values()],
            "heard_agent_turns": [s.speech_id for s in self.heard_agent_turns],
            "interrupted_agent_turns": [s.speech_id for s in self.interrupted_agent_turns],
        }
