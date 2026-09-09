"""Salon appointment-resolution adapter."""

from __future__ import annotations

from typing import ClassVar

from ..resolution.hypotheses import Hypothesis
from ..resolution.state import ResolutionState
from ..tools.types import Subject, ToolResult
from .base import COMMON_NEGATIONS, DomainAdapter, ToolDefinition, goal, rx


class SalonAdapter(DomainAdapter):
    domain_id = "salon"
    label = "Salon appointment support"
    default_fixture = "salon_appointment_changed"
    issue_type = "APPOINTMENT_RECORD_CONFLICT"
    issue_summary = "Confirmed salon appointment is missing, cancelled, or changed incorrectly"
    opening_line = "Salon support. How can I help you today?"
    escalation_destination = "Appointment operations"
    primary_delay_tool = "check_appointment_record"
    tools = (
        ToolDefinition(
            "list_appointments", Subject.APPOINTMENT, "list the customer's synthetic appointments"
        ),
        ToolDefinition(
            "get_appointment",
            Subject.APPOINTMENT,
            "get an appointment by full or spoken synthetic ID",
        ),
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
            goal_ids=frozenset({"reschedule_appointment", "resolve_appointment_mismatch"}),
        ),
        ToolDefinition(
            "check_salon_availability",
            Subject.APPOINTMENT,
            "check availability for a requested appointment time",
        ),
        ToolDefinition(
            "change_appointment_service",
            Subject.APPOINTMENT,
            "change the service on an existing appointment",
            True,
            goal_ids=frozenset({"change_appointment_service"}),
        ),
        ToolDefinition(
            "cancel_appointment",
            Subject.APPOINTMENT,
            "cancel an existing appointment",
            True,
            goal_ids=frozenset({"cancel_appointment"}),
        ),
        ToolDefinition(
            "rebook_appointment",
            Subject.APPOINTMENT,
            "rebook an affected appointment",
            True,
            goal_ids=frozenset({"rebook_appointment", "resolve_appointment_mismatch"}),
        ),
    )
    goals = (
        goal(
            "view_appointment_details",
            "Retrieve appointment details such as ID, service, provider, date, or time",
            r"\b(?:what|which|when|who|tell me|show|details?|id|service|provider|stylist|time|date)\b.*\b(?:appointment|salon|service|provider|stylist)\b|\bappointment\b.*\b(?:details?|id|service|provider|stylist|time|date)\b",
            subjects=frozenset({Subject.APPOINTMENT}),
        ),
        goal(
            "change_appointment_service",
            "Change the service on an appointment",
            r"\b(?:change|switch)\b.*\b(?:service|haircut|treatment)\b",
            subjects=frozenset({Subject.APPOINTMENT}),
        ),
        goal(
            "cancel_appointment",
            "Cancel an existing appointment",
            r"\bcancel\b.*\bappointment\b",
            subjects=frozenset({Subject.APPOINTMENT}),
        ),
        goal(
            "rebook_appointment",
            "Rebook an affected appointment",
            r"\b(?:rebook|book again|replacement)\b",
            subjects=frozenset({Subject.APPOINTMENT, Subject.MERCHANT_RECORD}),
        ),
        goal(
            "reschedule_appointment",
            "Reschedule an existing appointment",
            r"\b(?:move|reschedule|prepone|postpone|earlier|later)\b",
            subjects=frozenset({Subject.APPOINTMENT}),
        ),
        goal(
            "resolve_appointment_mismatch",
            "Resolve an appointment record mismatch",
            r"\b(?:missing|changed|cancelled|canceled|wrong|mismatch|cannot find)\b.*\bappointment\b",
            subjects=frozenset({Subject.APPOINTMENT, Subject.MERCHANT_RECORD}),
        ),
        goal(
            "verify_appointment",
            "Find or verify an existing appointment",
            r"\b(?:find|verify|check|locate)\b.*\bappointment\b",
            subjects=frozenset({Subject.APPOINTMENT, Subject.MERCHANT_RECORD}),
        ),
    )
    diagnostic_goal_ids = frozenset({"resolve_appointment_mismatch"})
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

    async def invoke(self, backend, tool_name: str, **kwargs):
        if tool_name == "list_appointments":
            return await backend.list_records(tool_name, "appointment")
        if tool_name == "get_appointment":
            return await backend.get_record(
                tool_name, "appointment", kwargs.get("appointment_id", "")
            )
        if tool_name == "check_appointment_record":

            def appointment():
                record = backend.sandbox.get_record(
                    backend.customer_id, self.domain_id, "appointment"
                )
                return {
                    "customer_id": backend.customer_id,
                    "appointment_status": record.get("status", "UNKNOWN"),
                    **record,
                }

            return await backend.call(tool_name, appointment)
        if tool_name == "check_appointment_history":

            def history():
                record = backend.sandbox.get_record(
                    backend.customer_id, self.domain_id, "appointment"
                )
                return {
                    "customer_id": backend.customer_id,
                    "change_cause": record.get("change_cause", "NONE"),
                    **record,
                }

            return await backend.call(tool_name, history)
        if tool_name == "check_salon_availability":

            def availability():
                record = backend.sandbox.get_record(
                    backend.customer_id, self.domain_id, "appointment"
                )
                return {
                    "customer_id": backend.customer_id,
                    **backend.sandbox.check_availability(
                        self.domain_id,
                        record["salon"],
                        record["date"],
                        kwargs.get("requested_time", ""),
                    ),
                }

            return await backend.call(tool_name, availability)
        if tool_name == "change_appointment_service":
            return await backend.update_record(
                tool_name, "appointment", {"service": kwargs.get("service")}
            )
        if tool_name == "cancel_appointment":
            return await backend.update_record(
                tool_name, "appointment", {"status": "CANCELLED"}, action_status="CANCELLED"
            )
        if tool_name == "rebook_appointment":
            return await backend.update_record(
                tool_name,
                "appointment",
                {"status": "CONFIRMED", "time": kwargs.get("new_time")},
                action_status="REBOOKED",
            )
        if tool_name == "reschedule_appointment" and kwargs:
            return await backend.update_record(
                tool_name, "appointment", {"time": kwargs.get("new_time")}
            )
        if tool_name == "reschedule_appointment":
            return await backend.update_record(
                tool_name, "appointment", {"status": "CONFIRMED"}, action_status="RESCHEDULED"
            )
        return await super().invoke(backend, tool_name, **kwargs)

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
