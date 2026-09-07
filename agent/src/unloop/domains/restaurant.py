"""Restaurant reservation-support adapter; not a discovery concierge."""

from __future__ import annotations

from typing import ClassVar

from ..resolution.hypotheses import Hypothesis
from ..resolution.state import ResolutionState
from ..tools.types import Subject, ToolResult
from .base import COMMON_NEGATIONS, DomainAdapter, ToolDefinition, rx


class RestaurantAdapter(DomainAdapter):
    domain_id = "restaurant"
    label = "Restaurant reservation support"
    default_fixture = "restaurant_missing_reservation"
    issue_type = "RESERVATION_NOT_FOUND"
    issue_summary = "Customer has confirmation but the restaurant cannot find the reservation"
    opening_line = "I can help reconcile that reservation. Is the restaurant saying no booking appears under the confirmation?"
    escalation_destination = "Restaurant reservation operations"
    primary_delay_tool = "check_platform_reservation"
    tools = (
        ToolDefinition(
            "check_platform_reservation",
            Subject.RESERVATION,
            "check the platform confirmation record",
        ),
        ToolDefinition(
            "check_restaurant_record",
            Subject.MERCHANT_RECORD,
            "check the restaurant booking ledger",
        ),
        ToolDefinition(
            "rebook_reservation",
            Subject.RESERVATION,
            "create a corrective replacement booking",
            True,
            requires_hypothesis="RESERVATION_SYNC_FAILURE",
        ),
    )
    hypothesis_subjects: ClassVar[dict[str, frozenset[Subject]]] = {
        "RESTAURANT_HAS_BOOKING": frozenset({Subject.MERCHANT_RECORD}),
        "PLATFORM_CONFIRMATION_INVALID": frozenset({Subject.RESERVATION}),
        "RESERVATION_SYNC_FAILURE": frozenset({Subject.RESERVATION, Subject.MERCHANT_RECORD}),
        "RESERVATION_DETAILS_MISMATCH": frozenset({Subject.RESERVATION, Subject.MERCHANT_RECORD}),
    }
    denial_rules = (
        (
            "RESTAURANT_HAS_BOOKING",
            rx(
                r"\brestaurant\b[^.?!]{0,35}\b(?:cannot|can'?t|doesn'?t|does not|couldn'?t)\b[^.?!]{0,20}\b(?:find|see|locate|have)\b[^.?!]{0,20}\b(?:booking|reservation)\b"
            ),
            frozenset({Subject.MERCHANT_RECORD}),
        ),
    )
    evidence_patterns = (
        (
            rx(r"\b(?:confirmation|confirmed|confirmation email|confirmation message)\b"),
            "caller has a platform confirmation",
        ),
    )
    redirects = (
        (
            rx(
                r"\bcheck\b[^.?!]{0,25}\brestaurant(?:'s)?\b[^.?!]{0,20}\b(?:record|system|booking)\b"
            ),
            Subject.MERCHANT_RECORD,
        ),
    )
    branch_phrases: ClassVar[dict[str, str]] = {
        "platform_record": "the platform confirmation",
        "merchant_record": "the restaurant's booking record",
        "reconciliation": "the record mismatch",
    }
    remediation_actions = frozenset({"rebook_reservation"})
    safety_boundary = "Resolve this existing reservation only; do not recommend restaurants or act as a discovery assistant."

    def build_hypotheses(self) -> list[Hypothesis]:
        return [
            Hypothesis(
                "RESTAURANT_HAS_BOOKING",
                "The restaurant already has the reservation",
                branch="merchant_record",
                assertion_patterns=[
                    rx(
                        r"\brestaurant\b[^.?!]{0,30}\b(?:has|can see|found)\b[^.?!]{0,20}\b(?:booking|reservation)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "PLATFORM_CONFIRMATION_INVALID",
                "The platform confirmation is invalid",
                branch="platform_record",
                assertion_patterns=[
                    rx(
                        r"\bconfirmation\b[^.?!]{0,30}\b(?:invalid|wrong|not valid|doesn'?t exist)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "RESERVATION_SYNC_FAILURE",
                "The reservation failed to sync to the restaurant",
                branch="reconciliation",
                assertion_patterns=[
                    rx(
                        r"\b(?:reservation|booking)\b[^.?!]{0,40}\b(?:sync|transfer)\b[^.?!]{0,20}\b(?:failed|failure|missing)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                "RESERVATION_DETAILS_MISMATCH",
                "The restaurant record uses conflicting booking details",
                branch="reconciliation",
                assertion_patterns=[
                    rx(
                        r"\b(?:booking|reservation)\b[^.?!]{0,35}\b(?:details|date|time|name)\b[^.?!]{0,20}\b(?:mismatch|different|conflict|wrong)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
        ]

    def absorb(self, state: ResolutionState, result: ToolResult) -> None:
        p = result.payload
        if result.tool_name == "check_platform_reservation":
            status = str(p.get("platform_status", "")).upper()
            state.confirm_fact("platform_reservation_status", status)
            if status == "CONFIRMED":
                state.reject_hypothesis(
                    "PLATFORM_CONFIRMATION_INVALID",
                    self.evidence(state, result, "platform record is confirmed", supports=False),
                )
        elif result.tool_name == "check_restaurant_record":
            status = str(p.get("restaurant_status", "")).upper()
            state.confirm_fact("restaurant_record_status", status)
            if status == "MISSING":
                state.reject_hypothesis(
                    "RESTAURANT_HAS_BOOKING",
                    self.evidence(
                        state, result, "restaurant ledger has no reservation", supports=False
                    ),
                )
                state.support_hypothesis(
                    "RESERVATION_SYNC_FAILURE",
                    self.evidence(
                        state,
                        result,
                        "confirmed platform booking is missing at restaurant",
                        supports=True,
                    ),
                )
                state.set_strategy(
                    "investigate_reconciliation", reason="cross-system mismatch confirmed"
                )
        elif result.tool_name == "rebook_reservation":
            state.confirm_fact(
                "replacement_reservation_status", str(p.get("action_status", "UNKNOWN"))
            )

    def describe(self, result: ToolResult) -> str:
        p = result.payload
        if result.tool_name == "check_platform_reservation":
            return f"The platform reservation is {p.get('platform_status', 'unknown')}."
        if result.tool_name == "check_restaurant_record":
            return f"The restaurant record is {p.get('restaurant_status', 'unknown')}."
        if result.tool_name == "rebook_reservation":
            return f"The replacement reservation is {p.get('action_status', 'unknown')}."
        return super().describe(result)
