"""Hotel booking-reconciliation adapter; deliberately not a travel planner."""

from __future__ import annotations

from typing import ClassVar

from ..resolution.hypotheses import Hypothesis
from ..resolution.state import ResolutionState
from ..tools.types import Subject, ToolResult
from .base import COMMON_NEGATIONS, DomainAdapter, ToolDefinition, rx


class HotelAdapter(DomainAdapter):
    domain_id = "hotel"
    label = "Hotel booking support"
    default_fixture = "hotel_booking_conflict"
    issue_type = "HOTEL_BOOKING_NOT_FOUND"
    issue_summary = "Customer has a confirmed hotel booking but the hotel cannot locate it"
    opening_line = "I can help reconcile that booking. Is the hotel unable to find the confirmation at all, or are the details different?"
    escalation_destination = "Hotel partner reconciliation"
    primary_delay_tool = "check_platform_booking"
    tools = (
        ToolDefinition(
            "check_platform_booking", Subject.BOOKING, "check the platform booking record"
        ),
        ToolDefinition(
            "check_hotel_record", Subject.PARTNER_RECORD, "check the hotel's property record"
        ),
        ToolDefinition(
            "reconcile_hotel_booking",
            Subject.BOOKING,
            "push a corrective reconciliation to the hotel",
            True,
            requires_hypothesis="HOTEL_SYNC_FAILURE",
        ),
    )
    hypothesis_subjects: ClassVar[dict[str, frozenset[Subject]]] = {
        "HOTEL_HAS_BOOKING": frozenset({Subject.PARTNER_RECORD}),
        "PLATFORM_BOOKING_INVALID": frozenset({Subject.BOOKING}),
        "HOTEL_SYNC_FAILURE": frozenset({Subject.BOOKING, Subject.PARTNER_RECORD}),
        "HOTEL_DETAILS_CONFLICT": frozenset({Subject.BOOKING, Subject.PARTNER_RECORD}),
    }
    denial_rules = (
        (
            "HOTEL_HAS_BOOKING",
            rx(
                r"\bhotel\b[^.?!]{0,35}\b(?:cannot|can'?t|doesn'?t|does not|couldn'?t)\b[^.?!]{0,20}\b(?:find|see|locate|have)\b[^.?!]{0,20}\b(?:booking|reservation)\b"
            ),
            frozenset({Subject.PARTNER_RECORD}),
        ),
    )
    evidence_patterns = (
        (
            rx(r"\b(?:confirmation|confirmed|voucher|booking email)\b"),
            "caller has a hotel booking confirmation",
        ),
    )
    redirects = (
        (
            rx(r"\bcheck\b[^.?!]{0,25}\bhotel(?:'s)?\b[^.?!]{0,20}\b(?:record|system|booking)\b"),
            Subject.PARTNER_RECORD,
        ),
    )
    branch_phrases: ClassVar[dict[str, str]] = {
        "platform_booking": "the platform booking record",
        "hotel_record": "the hotel's property record",
        "reconciliation": "the conflict between those records",
    }
    remediation_actions = frozenset({"reconcile_hotel_booking"})
    safety_boundary = "Resolve this existing booking only; do not search hotels, plan travel, or make unrelated bookings."

    def build_hypotheses(self) -> list[Hypothesis]:
        return [
            Hypothesis(
                "HOTEL_HAS_BOOKING",
                "The hotel already has the booking",
                branch="hotel_record",
                assertion_patterns=[
                    rx(
                        r"\bhotel\b[^.?!]{0,30}\b(?:has|can see|found)\b[^.?!]{0,20}\b(?:booking|reservation)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "PLATFORM_BOOKING_INVALID",
                "The platform booking confirmation is invalid",
                branch="platform_booking",
                assertion_patterns=[
                    rx(
                        r"\b(?:booking|confirmation)\b[^.?!]{0,30}\b(?:invalid|not valid|wrong|doesn'?t exist)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "HOTEL_SYNC_FAILURE",
                "The booking failed to sync to the hotel",
                branch="reconciliation",
                assertion_patterns=[
                    rx(r"\bbooking\b[^.?!]{0,35}\bsync\b[^.?!]{0,20}\b(?:failed|failure|missing)\b")
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "HOTEL_DETAILS_CONFLICT",
                "The hotel record conflicts with the confirmed booking details",
                branch="reconciliation",
                assertion_patterns=[
                    rx(
                        r"\b(?:booking|hotel)\b[^.?!]{0,35}\b(?:details|dates|room|guest)\b[^.?!]{0,20}\b(?:conflict|mismatch|different|wrong)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
        ]

    def absorb(self, state: ResolutionState, result: ToolResult) -> None:
        p = result.payload
        if result.tool_name == "check_platform_booking":
            status = str(p.get("platform_status", "")).upper()
            state.confirm_fact("platform_booking_status", status, detail=dict(p))
            if status == "CONFIRMED":
                state.reject_hypothesis(
                    "PLATFORM_BOOKING_INVALID",
                    self.evidence(state, result, "platform booking is confirmed", supports=False),
                )
        elif result.tool_name == "check_hotel_record":
            status = str(p.get("hotel_status", "")).upper()
            state.confirm_fact("hotel_record_status", status, detail=dict(p))
            if status == "MISSING":
                state.reject_hypothesis(
                    "HOTEL_HAS_BOOKING",
                    self.evidence(
                        state, result, "hotel property record is missing", supports=False
                    ),
                )
                state.support_hypothesis(
                    "HOTEL_SYNC_FAILURE",
                    self.evidence(
                        state,
                        result,
                        "confirmed booking is absent from hotel system",
                        supports=True,
                    ),
                )
                state.set_strategy(
                    "investigate_reconciliation", reason="hotel record conflict confirmed"
                )
            elif status == "CONFLICT":
                state.support_hypothesis(
                    "HOTEL_DETAILS_CONFLICT",
                    self.evidence(state, result, "hotel record details conflict", supports=True),
                )
        elif result.tool_name == "reconcile_hotel_booking":
            state.confirm_fact(
                "hotel_reconciliation_status",
                str(p.get("action_status", "UNKNOWN")),
                detail=dict(p),
            )

    def describe(self, result: ToolResult) -> str:
        p = result.payload
        if result.tool_name == "check_platform_booking":
            return f"The platform booking is {p.get('platform_status', 'unknown')}."
        if result.tool_name == "check_hotel_record":
            return f"The hotel's record is {p.get('hotel_status', 'unknown')}."
        if result.tool_name == "reconcile_hotel_booking":
            return f"The hotel reconciliation is {p.get('action_status', 'unknown')}."
        return super().describe(result)
