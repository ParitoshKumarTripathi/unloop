"""Structured human handoff.

The point of escalating is that the caller should not have to start again. A generic
conversation summary fails at that: it tells the human what was *said*, not what was
*established*, and the human re-checks the card status the caller already refuted.

:func:`build_handoff_packet` serialises the resolution state instead — what is
confirmed, what was ruled out and on whose authority, what the caller corrected, what
was already tried, and where this should go next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..resolution.hypotheses import HypothesisStatus
from ..resolution.state import EscalationStatus, ResolutionState


@dataclass
class HandoffPacket:
    """Everything the next human needs, and nothing they would have to re-derive."""

    case_id: str | None
    session_id: str
    state_version: int
    issue: str
    confirmed: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    observed: list[dict[str, Any]] = field(default_factory=list)
    user_corrections: list[dict[str, Any]] = field(default_factory=list)
    attempted: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    recommended_destination: str = "General support"
    conflicts: list[str] = field(default_factory=list)
    stale_results_fenced: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "state_version": self.state_version,
            "issue": self.issue,
            "confirmed": self.confirmed,
            "rejected": self.rejected,
            "observed": self.observed,
            "user_corrections": self.user_corrections,
            "attempted": self.attempted,
            "open_questions": self.open_questions,
            "recommended_destination": self.recommended_destination,
            "conflicts": self.conflicts,
            "stale_results_fenced": self.stale_results_fenced,
        }

    def to_spoken_summary(self) -> str:
        """A short, ear-friendly version of what is being passed along.

        Deliberately not a recitation of the packet. The caller needs to know their
        context travels with them, not to hear a list of field names.
        """
        ruled_out = ", ".join(r["label"].lower() for r in self.rejected[:2])
        parts = [f"I'm passing this to {self.recommended_destination.lower()}."]
        if ruled_out:
            parts.append(f"They'll see that we already ruled out {ruled_out}.")
        if self.observed:
            parts.append(f"They'll also see {self.observed[0]['summary'].lower()}.")
        parts.append("You won't need to explain this again.")
        return " ".join(parts)


#: Where a case should go, based on what survived triage.
_DESTINATIONS: tuple[tuple[str, str], ...] = (
    ("OTP_DELIVERY_FAILED", "OTP and SMS delivery support"),
    ("SMS_PROVIDER_INCIDENT", "OTP and SMS delivery support"),
    ("OTP_NOT_GENERATED", "Payment authorisation support"),
    ("MOBILE_NOT_REGISTERED", "Customer records team"),
    ("ONLINE_TXN_DISABLED", "Card services"),
    ("CARD_BLOCKED", "Card services"),
)


def recommend_destination(state: ResolutionState) -> str:
    """Pick a queue from the surviving hypotheses, best-supported first."""
    ranked = sorted(
        (h for h in state.hypotheses.values() if not h.is_rejected),
        key=lambda h: (h.status is HypothesisStatus.SUPPORTED, h.confidence),
        reverse=True,
    )
    for hypothesis in ranked:
        for hypothesis_id, destination in _DESTINATIONS:
            if hypothesis.id == hypothesis_id and (
                hypothesis.status is HypothesisStatus.SUPPORTED or hypothesis.confidence > 0.5
            ):
                return destination
    return "General banking support"


def build_handoff_packet(state: ResolutionState) -> HandoffPacket:
    """Serialise the resolution state into a human-usable packet."""
    confirmed = [
        {"key": f.key, "value": f.value, "source": f.source.value} for f in state.confirmed_facts
    ]

    rejected = [
        {
            "id": h.id,
            "label": h.label,
            "rejected_at_version": h.rejected_at_version,
            "because": [e.summary for e in h.contradicting_evidence],
        }
        for h in state.rejected_hypotheses
    ]

    observed = [
        {"id": h.id, "label": h.label, "summary": h.label, "confidence": round(h.confidence, 2)}
        for h in state.hypotheses.values()
        if h.status is HypothesisStatus.SUPPORTED
    ]

    corrections = [
        {
            "claim": c.claim,
            "evidence": c.evidence,
            "target": c.target_hypothesis,
            "at_version": c.state_version_after,
        }
        for c in state.user_corrections
    ]

    # Deduplicate while preserving order: the human wants to know what was tried,
    # not how many times the engine retried it.
    attempted: list[str] = []
    for action in state.attempted_actions:
        if action not in attempted:
            attempted.append(action)

    open_questions: list[str] = []
    for hypothesis in state.hypotheses.values():
        if hypothesis.status is HypothesisStatus.ACTIVE and hypothesis.times_suggested_to_user == 0:
            open_questions.append(f"Not yet checked: {hypothesis.label.lower()}")

    conflicts = [
        str(event.meta.get("detail"))
        for event in state.recorder.events
        if event.meta.get("signal") == "caller_tool_conflict" and event.meta.get("detail")
    ]

    failed_tools = [t.tool_name for t in state.completed_tools if not t.succeeded]
    for tool_name in dict.fromkeys(failed_tools):
        open_questions.append(f"Could not complete: {tool_name}")

    return HandoffPacket(
        case_id=state.case_id,
        session_id=state.session_id,
        state_version=state.state_version,
        issue=state.issue_summary or state.issue_type,
        confirmed=confirmed,
        rejected=rejected,
        observed=observed,
        user_corrections=corrections,
        attempted=attempted,
        open_questions=open_questions,
        recommended_destination=recommend_destination(state),
        conflicts=conflicts,
        stale_results_fenced=sum(1 for t in state.completed_tools if t.stale),
    )


def mark_escalated(state: ResolutionState, reason: str) -> None:
    state.set_escalation(EscalationStatus.CREATED, reason=reason)
