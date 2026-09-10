"""Hotel booking-reconciliation adapter; deliberately not a travel planner."""

from __future__ import annotations

from typing import ClassVar

from ..resolution.hypotheses import Hypothesis
from ..resolution.state import ResolutionState
from ..tools.types import Subject, ToolResult
from .base import COMMON_NEGATIONS, DomainAdapter, ToolDefinition, goal, rx
from .scheduling import target_date_range


class HotelAdapter(DomainAdapter):
    domain_id = "hotel"
    label = "Hotel booking support"
    default_fixture = "hotel_booking_conflict"
    issue_type = "HOTEL_BOOKING_NOT_FOUND"
    issue_summary = "Customer has a confirmed hotel booking but the hotel cannot locate it"
    opening_line = "Hotel support. How can I help you today?"
    escalation_destination = "Hotel partner reconciliation"
    primary_delay_tool = "check_platform_booking"
    tools = (
        ToolDefinition("list_bookings", Subject.BOOKING, "list the customer's synthetic bookings"),
        ToolDefinition(
            "get_booking", Subject.BOOKING, "get a booking by full or spoken synthetic ID"
        ),
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
        ToolDefinition(
            "check_hotel_availability",
            Subject.BOOKING,
            "check availability using separate YYYY-MM-DD check-in and check-out values",
        ),
        ToolDefinition(
            "change_hotel_dates",
            Subject.BOOKING,
            "change check-in and/or check-out with separate YYYY-MM-DD values",
            True,
            goal_ids=frozenset({"change_booking_dates"}),
        ),
        ToolDefinition(
            "change_hotel_guest_count",
            Subject.BOOKING,
            "change the guest count on an existing booking",
            True,
            goal_ids=frozenset({"change_guest_count"}),
        ),
        ToolDefinition(
            "cancel_hotel_booking",
            Subject.BOOKING,
            "cancel an existing booking",
            True,
            goal_ids=frozenset({"cancel_booking"}),
        ),
        ToolDefinition(
            "rebook_hotel_booking",
            Subject.BOOKING,
            "rebook an affected existing booking",
            True,
            goal_ids=frozenset({"rebook_booking", "resolve_booking_mismatch"}),
        ),
    )
    goals = (
        goal(
            "view_booking_details",
            "Retrieve booking details such as ID, dates, room, or guest count",
            r"\b(?:what|which|when|how many|tell me|show|details?|id|room|guest|check.?in|check.?out)\b.*\b(?:booking|reservation|hotel|guests?)\b",
            subjects=frozenset({Subject.BOOKING}),
        ),
        goal(
            "change_guest_count",
            "Change the guest count on a hotel booking",
            r"\b(?:change|make|update|increase|decrease|add|remove)\b.*\b(?:guests?|people|party size)\b",
            subjects=frozenset({Subject.BOOKING}),
        ),
        goal(
            "cancel_booking",
            "Cancel an existing hotel booking",
            r"\bcancel\b.*\b(?:hotel|booking|reservation|it)\b",
            subjects=frozenset({Subject.BOOKING}),
        ),
        goal(
            "rebook_booking",
            "Rebook an affected hotel stay",
            r"\b(?:rebook|book(?:\s+it)? again|replacement)\b",
            subjects=frozenset({Subject.BOOKING, Subject.PARTNER_RECORD}),
        ),
        goal(
            "change_booking_dates",
            "Change dates on an existing hotel booking",
            r"\b(?:change|move|extend|shorten|prepone|postpone)\b.*\b(?:date|stay|booking|check.?in|check.?out)\b|\b(?:extend|shorten|prepone|postpone)\b",
            subjects=frozenset({Subject.BOOKING}),
        ),
        goal(
            "resolve_booking_mismatch",
            "Resolve a hotel booking mismatch",
            r"\b(?:missing|cannot|can'?t|mismatch|conflict|not find)\b.*\b(?:booking|reservation)\b",
            subjects=frozenset({Subject.BOOKING, Subject.PARTNER_RECORD}),
        ),
        goal(
            "verify_booking",
            "Find or verify an existing hotel booking",
            r"\b(?:find|verify|check|locate)\b.*\b(?:booking|reservation)\b",
            subjects=frozenset({Subject.BOOKING, Subject.PARTNER_RECORD}),
        ),
    )
    diagnostic_goal_ids = frozenset({"resolve_booking_mismatch"})
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

    async def invoke(self, backend, tool_name: str, **kwargs):
        if tool_name == "list_bookings":
            return await backend.list_records(tool_name, "booking")
        if tool_name == "get_booking":
            return await backend.get_record(tool_name, "booking", kwargs.get("booking_id", ""))
        if tool_name == "check_platform_booking":

            def platform():
                record = backend.sandbox.get_record(backend.customer_id, self.domain_id, "booking")
                return {
                    "customer_id": backend.customer_id,
                    "platform_status": record.get("status", "UNKNOWN"),
                    **record,
                }

            return await backend.call(tool_name, platform)
        if tool_name == "check_hotel_record":

            def partner():
                record = backend.sandbox.get_record(backend.customer_id, self.domain_id, "booking")
                status = "MISSING" if record.get("partner_status") == "MISSING" else "FOUND"
                return {"customer_id": backend.customer_id, "hotel_status": status, **record}

            return await backend.call(tool_name, partner)
        if tool_name == "reconcile_hotel_booking":

            def reconcile():
                current = backend.sandbox.get_record(backend.customer_id, self.domain_id, "booking")
                if current.get("partner_status") == "FOUND":
                    return {
                        "customer_id": backend.customer_id,
                        "action_status": "ALREADY_RECONCILED",
                        "already_in_requested_state": True,
                        "changed": False,
                        **current,
                    }
                record = backend.sandbox.update_record(
                    backend.customer_id,
                    self.domain_id,
                    "booking",
                    {"partner_status": "FOUND"},
                    action=tool_name,
                )
                return {
                    "customer_id": backend.customer_id,
                    "action_status": "RECONCILED",
                    "changed": True,
                    **record,
                }

            return await backend.call(tool_name, reconcile, mutates=True)
        if tool_name == "check_hotel_availability":

            def availability():
                record = backend.sandbox.get_record(backend.customer_id, self.domain_id, "booking")
                check_in, check_out = target_date_range(
                    record,
                    check_in=kwargs.get("check_in"),
                    check_out=kwargs.get("check_out"),
                )
                return {
                    "customer_id": backend.customer_id,
                    "hotel": record["hotel"],
                    **backend.sandbox.check_date_range_availability(
                        self.domain_id, record["hotel"], check_in, check_out
                    ),
                }

            return await backend.call(tool_name, availability)
        if tool_name == "change_hotel_dates":
            return await self._change_dates(backend, tool_name, "UPDATED", **kwargs)
        if tool_name == "change_hotel_guest_count":
            return await backend.update_record(
                tool_name, "booking", {"guest_count": kwargs.get("guest_count")}
            )
        if tool_name == "cancel_hotel_booking":
            return await backend.update_record(
                tool_name, "booking", {"status": "CANCELLED"}, action_status="CANCELLED"
            )
        if tool_name == "rebook_hotel_booking":
            return await self._change_dates(backend, tool_name, "REBOOKED", rebook=True, **kwargs)
        return await super().invoke(backend, tool_name, **kwargs)

    async def _change_dates(
        self, backend, tool_name: str, action_status: str, *, rebook: bool = False, **kwargs
    ):
        def change():
            current = backend.sandbox.get_record(backend.customer_id, self.domain_id, "booking")
            check_in, check_out = target_date_range(
                current,
                check_in=kwargs.get("check_in"),
                check_out=kwargs.get("check_out"),
            )
            desired_status = "CONFIRMED" if rebook else current["status"]
            if (
                current["check_in"] == check_in
                and current["check_out"] == check_out
                and current["status"] == desired_status
            ):
                return {
                    "customer_id": backend.customer_id,
                    "action_status": f"ALREADY_{action_status}",
                    "already_in_requested_state": True,
                    "changed": False,
                    **current,
                }
            availability = backend.sandbox.check_date_range_availability(
                self.domain_id, current["hotel"], check_in, check_out
            )
            if availability["availability"] != "AVAILABLE":
                return {
                    "customer_id": backend.customer_id,
                    "action_status": "UNAVAILABLE",
                    "requested_check_in": check_in,
                    "requested_check_out": check_out,
                    "unavailable_dates": availability["unavailable_dates"],
                    **current,
                }
            updated = backend.sandbox.update_record(
                backend.customer_id,
                self.domain_id,
                "booking",
                {"status": desired_status, "check_in": check_in, "check_out": check_out},
                action=tool_name,
            )
            return {
                "customer_id": backend.customer_id,
                "action_status": action_status,
                "changed": True,
                **updated,
            }

        return await backend.call(tool_name, change, mutates=True)

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
        if result.tool_name == "check_hotel_availability":
            return (
                f"The stay from {p.get('check_in')} to {p.get('check_out')} is "
                f"{str(p.get('availability', 'unknown')).lower()}."
            )
        if result.tool_name in {"change_hotel_dates", "rebook_hotel_booking"}:
            if p.get("action_status") == "UNAVAILABLE":
                return (
                    f"The requested stay from {p.get('requested_check_in')} through "
                    f"{p.get('requested_check_out')} is unavailable. Nothing was changed."
                )
            return (
                f"The booking dates are now {p.get('check_in')} through {p.get('check_out')}; "
                f"the action is {str(p.get('action_status', 'updated')).lower()}."
            )
        if result.tool_name == "change_hotel_guest_count":
            return f"The hotel guest count is now {p.get('guest_count')}."
        return super().describe(result)
