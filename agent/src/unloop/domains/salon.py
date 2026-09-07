"""Salon appointment-resolution adapter."""

from __future__ import annotations

from typing import ClassVar

from ..resolution.hypotheses import Hypothesis
from ..resolution.state import ResolutionState
from ..tools.types import Subject, ToolResult
from .base import COMMON_NEGATIONS, DomainAdapter, ToolDefinition, rx


class SalonAdapter(DomainAdapter):
    domain_id = "salon"
    label = "Salon appointment support"
    default_fixture = "salon_appointment_changed"
    issue_type = "APPOINTMENT_RECORD_CONFLICT"
    issue_summary = "Confirmed salon appointment is missing, cancelled, or changed incorrectly"
    opening_line = "I can help fix the appointment record. What does the salon say is different from your confirmation?"
    escalation_destination = "Appointment operations"
    primary_delay_tool = "check_appointment_record"
    tools = (
        ToolDefinition(
            "check_appointment_record", Subject.APPOINTMENT, "check the confirmed appointment"
        ),
        ToolDefinition(
            "check_appointment_history", Subject.MERCHANT_RECORD, "audit changes and cancellations"
        ),
        ToolDefinition(
            "reschedule_appointment",
            Subject.APPOINTMENT,
            "correctively reschedule the affected appointment",
            True,
            requires_hypothesis="APPOINTMENT_CHANGED_IN_ERROR",
        ),
    )
    hypothesis_subjects: ClassVar[dict[str, frozenset[Subject]]] = {
        "APPOINTMENT_UNCHANGED": frozenset({Subject.APPOINTMENT}),
        "MERCHANT_CANCELLED_APPOINTMENT": frozenset({Subject.MERCHANT_RECORD}),
        "APPOINTMENT_CHANGED_IN_ERROR": frozenset({Subject.APPOINTMENT, Subject.MERCHANT_RECORD}),
        "APPOINTMENT_SYNC_FAILURE": frozenset({Subject.APPOINTMENT, Subject.MERCHANT_RECORD}),
    }
    denial_rules = (
        (
            "APPOINTMENT_UNCHANGED",
            rx(
                r"\bappointment\b[^.?!]{0,35}\b(?:was|has been|got)\b[^.?!]{0,20}\b(?:changed|cancelled|canceled|moved)\b[^.?!]{0,20}\b(?:wrong|incorrect|without)\b|\bmerchant\b[^.?!]{0,30}\b(?:cannot|can'?t|doesn'?t)\b[^.?!]{0,20}\b(?:find|see)\b[^.?!]{0,20}\bappointment\b"
            ),
            frozenset({Subject.APPOINTMENT}),
        ),
    )
    evidence_patterns = (
        (
            rx(r"\b(?:confirmation|confirmed|message|email)\b"),
            "caller has an appointment confirmation",
        ),
    )
    redirects = (
        (
            rx(r"\b(?:check|audit)\b[^.?!]{0,25}\b(?:change|history|cancel)\b"),
            Subject.MERCHANT_RECORD,
        ),
    )
    branch_phrases: ClassVar[dict[str, str]] = {
        "appointment_record": "the current appointment record",
        "change_history": "who changed the appointment",
        "reconciliation": "the appointment mismatch",
    }
    remediation_actions = frozenset({"reschedule_appointment"})
    safety_boundary = "Resolve the affected appointment only; do not recommend salons or create unrelated appointments."

    def build_hypotheses(self) -> list[Hypothesis]:
        return [
            Hypothesis(
                "APPOINTMENT_UNCHANGED",
                "The appointment is still recorded exactly as confirmed",
                branch="appointment_record",
                assertion_patterns=[
                    rx(
                        r"\bappointment\b[^.?!]{0,35}\b(?:is|remains|still)\b[^.?!]{0,20}\b(?:confirmed|unchanged|correct)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "MERCHANT_CANCELLED_APPOINTMENT",
                "The salon deliberately cancelled the appointment",
                branch="change_history",
                assertion_patterns=[
                    rx(
                        r"\b(?:salon|merchant)\b[^.?!]{0,30}\b(?:cancelled|canceled)\b[^.?!]{0,20}\bappointment\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "APPOINTMENT_CHANGED_IN_ERROR",
                "The appointment was changed incorrectly",
                branch="change_history",
                assertion_patterns=[
                    rx(
                        r"\bappointment\b[^.?!]{0,35}\b(?:changed|moved|cancelled|canceled)\b[^.?!]{0,20}\b(?:incorrectly|by mistake|in error)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "APPOINTMENT_SYNC_FAILURE",
                "The confirmed appointment failed to sync to the salon",
                branch="reconciliation",
                assertion_patterns=[
                    rx(
                        r"\bappointment\b[^.?!]{0,35}\bsync\b[^.?!]{0,20}\b(?:failed|failure|missing)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
        ]

    def absorb(self, state: ResolutionState, result: ToolResult) -> None:
        p = result.payload
        if result.tool_name == "check_appointment_record":
            status = str(p.get("appointment_status", "")).upper()
            state.confirm_fact("appointment_status", status, detail=dict(p))
            if status in {"CHANGED", "CANCELLED", "MISSING"}:
                state.reject_hypothesis(
                    "APPOINTMENT_UNCHANGED",
                    self.evidence(
                        state, result, f"appointment record is {status.lower()}", supports=False
                    ),
                )
        elif result.tool_name == "check_appointment_history":
            cause = str(p.get("change_cause", "")).upper()
            state.confirm_fact("appointment_change_cause", cause)
            if cause == "SYSTEM_ERROR":
                state.support_hypothesis(
                    "APPOINTMENT_CHANGED_IN_ERROR",
                    self.evidence(state, result, "audit shows a system error", supports=True),
                )
                state.set_strategy("correct_appointment", reason="erroneous change confirmed")
        elif result.tool_name == "reschedule_appointment":
            state.confirm_fact(
                "appointment_resolution", str(p.get("action_status", "UNKNOWN")), detail=dict(p)
            )

    def describe(self, result: ToolResult) -> str:
        p = result.payload
        if result.tool_name == "check_appointment_record":
            return f"The appointment record is {p.get('appointment_status', 'unknown')}."
        if result.tool_name == "check_appointment_history":
            return f"The change audit reports {p.get('change_cause', 'unknown')}."
        if result.tool_name == "reschedule_appointment":
            return f"The corrective reschedule is {p.get('action_status', 'unknown')}."
        return super().describe(result)
