"""Restaurant reservation-support adapter; not a discovery concierge."""

from __future__ import annotations

from typing import ClassVar

from ..resolution.hypotheses import Hypothesis
from ..resolution.state import ResolutionState
from ..tools.types import Subject, ToolResult
from .base import COMMON_NEGATIONS, DomainAdapter, ToolDefinition, goal, rx
from .scheduling import target_schedule


class RestaurantAdapter(DomainAdapter):
    domain_id = "restaurant"
    label = "Restaurant reservation support"
    default_fixture = "restaurant_missing_reservation"
    issue_type = "RESERVATION_NOT_FOUND"
    issue_summary = "Customer has confirmation but the restaurant cannot find the reservation"
    opening_line = "Restaurant support. How can I help you today?"
    escalation_destination = "Restaurant reservation operations"
    primary_delay_tool = "check_platform_reservation"
    tools = (
        ToolDefinition(
            "list_reservations", Subject.RESERVATION, "list the customer's existing reservations"
        ),
        ToolDefinition(
            "get_reservation",
            Subject.RESERVATION,
            "get one existing reservation by synthetic identifier",
        ),
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
            goal_ids=frozenset({"rebook_reservation", "resolve_confirmation_mismatch"}),
        ),
        ToolDefinition(
            "check_restaurant_availability",
            Subject.RESERVATION,
            "check availability for a requested reservation date and time, supplied separately",
            goal_ids=frozenset({"reschedule_reservation", "rebook_reservation"}),
        ),
        ToolDefinition(
            "reschedule_restaurant_reservation",
            Subject.RESERVATION,
            "move the existing reservation to a requested date and/or time, supplied separately",
            True,
            goal_ids=frozenset({"reschedule_reservation"}),
        ),
        ToolDefinition(
            "change_restaurant_party_size",
            Subject.RESERVATION,
            "change the party size while preserving other booking details",
            True,
            goal_ids=frozenset({"change_party_size"}),
        ),
        ToolDefinition(
            "cancel_restaurant_reservation",
            Subject.RESERVATION,
            "cancel the existing reservation",
            True,
            goal_ids=frozenset({"cancel_reservation"}),
        ),
        ToolDefinition(
            "create_reservation",
            Subject.RESERVATION,
            "create a corrective reservation for this customer",
            True,
            goal_ids=frozenset({"rebook_reservation"}),
        ),
    )
    goals = (
        goal(
            "view_reservation_details",
            "Retrieve reservation details such as ID, time, date, or party size",
            r"\b(?:what|which|when|how many|tell me|show|details?|id|time|date)\b.*\b(?:reservation|booking|table|people|persons?|guests?|party size)\b",
            subjects=frozenset({Subject.RESERVATION}),
        ),
        goal(
            "change_party_size",
            "Change the reservation party size",
            r"\b(?:change|make|update|increase|decrease|add|remove)\b.*\b(?:party size|people|persons?|guests?)\b",
            subjects=frozenset({Subject.RESERVATION}),
        ),
        goal(
            "cancel_reservation",
            "Cancel the existing reservation",
            r"\b(?:cancel|delete)\b.*\b(?:reservation|booking|table|it)\b",
            subjects=frozenset({Subject.RESERVATION}),
        ),
        goal(
            "rebook_reservation",
            "Rebook an affected reservation",
            r"\b(?:rebook|book(?:\s+it)? again|replacement booking)\b",
            subjects=frozenset({Subject.RESERVATION, Subject.MERCHANT_RECORD}),
        ),
        goal(
            "reschedule_reservation",
            "Reschedule the existing reservation",
            r"\b(?:move|reschedule|prepone|postpone|earlier|later|keep it at)\b",
            subjects=frozenset({Subject.RESERVATION}),
        ),
        goal(
            "resolve_confirmation_mismatch",
            "Resolve a reservation confirmation mismatch",
            r"\b(?:cannot|can'?t|doesn'?t|missing|mismatch|not find|confirmation)\b.*\b(?:reservation|booking|table)\b",
            subjects=frozenset({Subject.RESERVATION, Subject.MERCHANT_RECORD}),
        ),
        goal(
            "verify_reservation",
            "Find or verify the existing reservation",
            r"\b(?:find|verify|check|locate)\b.*\b(?:reservation|booking|table)\b",
            subjects=frozenset({Subject.RESERVATION, Subject.MERCHANT_RECORD}),
        ),
    )
    diagnostic_goal_ids = frozenset({"resolve_confirmation_mismatch"})
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

    async def invoke(self, backend, tool_name: str, **kwargs):
        if tool_name == "list_reservations":
            return await backend.call(
                tool_name,
                lambda: {
                    "customer_id": backend.customer_id,
                    "reservations": backend.sandbox.list_records(
                        backend.customer_id, self.domain_id, "reservation"
                    ),
                },
            )
        if tool_name == "get_reservation":
            return await backend.get_record(
                tool_name, "reservation", kwargs.get("reservation_id", "")
            )
        if tool_name == "check_platform_reservation":

            async def platform_record():
                record = backend.sandbox.get_record(
                    backend.customer_id, self.domain_id, "reservation"
                )
                return {
                    "customer_id": backend.customer_id,
                    "platform_status": record.get("status", "UNKNOWN"),
                    **record,
                }

            return await backend.call(tool_name, platform_record)
        if tool_name == "check_restaurant_record":

            async def restaurant_record():
                record = backend.sandbox.get_record(
                    backend.customer_id, self.domain_id, "reservation"
                )
                partner = record.get("partner_status", "FOUND")
                return {
                    "customer_id": backend.customer_id,
                    "restaurant_status": "MISSING" if partner == "MISSING" else "FOUND",
                    **record,
                }

            return await backend.call(tool_name, restaurant_record)
        if tool_name == "check_restaurant_availability":

            def availability():
                record = backend.sandbox.get_record(
                    backend.customer_id, self.domain_id, "reservation"
                )
                requested_date, requested_time = target_schedule(
                    record,
                    requested_date=kwargs.get("requested_date"),
                    requested_time=kwargs.get("requested_time"),
                )
                return {
                    "customer_id": backend.customer_id,
                    **backend.sandbox.check_availability(
                        self.domain_id,
                        record["restaurant"],
                        requested_date,
                        requested_time,
                    ),
                }

            return await backend.call(tool_name, availability)
        if tool_name == "reschedule_restaurant_reservation":

            def reschedule():
                current = backend.sandbox.get_record(
                    backend.customer_id, self.domain_id, "reservation"
                )
                target_date, target_time = target_schedule(
                    current,
                    requested_date=kwargs.get("new_date") or kwargs.get("requested_date"),
                    requested_time=kwargs.get("new_time") or kwargs.get("requested_time"),
                )
                if current["date"] == target_date and current["time"] == target_time:
                    return {
                        "customer_id": backend.customer_id,
                        "action_status": "ALREADY_SCHEDULED",
                        "already_in_requested_state": True,
                        "changed": False,
                        **current,
                    }
                availability = backend.sandbox.check_availability(
                    self.domain_id, current["restaurant"], target_date, target_time
                )
                if availability["availability"] != "AVAILABLE":
                    return {
                        "customer_id": backend.customer_id,
                        "action_status": "UNAVAILABLE",
                        "requested_date": target_date,
                        "requested_time": target_time,
                        "alternative_times": availability.get("alternative_times", []),
                        **current,
                    }
                updated = backend.sandbox.update_record(
                    backend.customer_id,
                    self.domain_id,
                    "reservation",
                    {"date": target_date, "time": target_time},
                    action=tool_name,
                )
                return {
                    "customer_id": backend.customer_id,
                    "action_status": "RESCHEDULED",
                    "changed": True,
                    **updated,
                }

            return await backend.call(tool_name, reschedule, mutates=True)
        if tool_name == "change_restaurant_party_size":
            return await backend.update_record(
                tool_name, "reservation", {"party_size": kwargs.get("party_size")}
            )
        if tool_name == "cancel_restaurant_reservation":
            return await backend.update_record(
                tool_name, "reservation", {"status": "CANCELLED"}, action_status="CANCELLED"
            )
        if tool_name == "rebook_reservation":

            def rebook():
                current = backend.sandbox.get_record(
                    backend.customer_id, self.domain_id, "reservation"
                )
                replacement_id = f"{current['reservation_id']}-R"
                replacement = {
                    **current,
                    "reservation_id": replacement_id,
                    "partner_status": "FOUND",
                    "status": "CONFIRMED",
                }
                backend.sandbox.create_record(
                    backend.customer_id, self.domain_id, "reservation", replacement_id, replacement
                )
                return {
                    "customer_id": backend.customer_id,
                    "action_status": "REBOOKED",
                    **replacement,
                }

            return await backend.call(tool_name, rebook, mutates=True)
        if tool_name == "create_reservation":

            def create():
                existing = backend.sandbox.list_records(
                    backend.customer_id, self.domain_id, "reservation"
                )
                record_id = f"RES-{802 + len(existing)}"
                record = {
                    "reservation_id": record_id,
                    "customer": "Demo Customer",
                    "restaurant": kwargs.get("restaurant", "Demo Bistro"),
                    "date": kwargs.get("date"),
                    "time": kwargs.get("time"),
                    "party_size": kwargs.get("party_size"),
                    "status": "CONFIRMED",
                    "partner_status": "FOUND",
                }
                backend.sandbox.create_record(
                    backend.customer_id, self.domain_id, "reservation", record_id, record
                )
                return {"customer_id": backend.customer_id, "action_status": "CREATED", **record}

            return await backend.call(tool_name, create, mutates=True)
        return await super().invoke(backend, tool_name, **kwargs)

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
        elif result.tool_name in {
            "reschedule_restaurant_reservation",
            "change_restaurant_party_size",
            "cancel_restaurant_reservation",
        }:
            if result.payload.get("action_status") == "UNAVAILABLE":
                return
            state.confirm_fact(
                "reservation_resolution", str(p.get("action_status", "UPDATED")), detail=dict(p)
            )

    def describe(self, result: ToolResult) -> str:
        p = result.payload
        if result.tool_name == "check_platform_reservation":
            return f"The platform reservation is {p.get('platform_status', 'unknown')}."
        if result.tool_name == "check_restaurant_record":
            return f"The restaurant record is {p.get('restaurant_status', 'unknown')}."
        if result.tool_name == "rebook_reservation":
            return f"The replacement reservation is {p.get('action_status', 'unknown')}."
        if result.tool_name == "check_restaurant_availability":
            summary = (
                f"The requested reservation on {p.get('date', 'the requested date')} at "
                f"{p.get('requested_time', 'the requested time')} is "
                f"{str(p.get('availability', 'unknown')).lower()}."
            )
            alternatives = p.get("alternative_times") or []
            if p.get("availability") == "UNAVAILABLE" and alternatives:
                summary += " Available times that day include " + ", ".join(alternatives) + "."
            return summary
        if result.tool_name == "reschedule_restaurant_reservation":
            if p.get("action_status") == "UNAVAILABLE":
                return (
                    f"The requested reservation on {p.get('requested_date')} at "
                    f"{p.get('requested_time')} is unavailable. Nothing was changed; the reservation "
                    f"remains on {p.get('date')} at {p.get('time')}."
                )
            return f"The reservation is now on {p.get('date')} at {p.get('time')}."
        if result.tool_name == "change_restaurant_party_size":
            return f"The reservation remains at {p.get('time', 'its existing time')} and the party size is now {p.get('party_size', 'updated')}."
        if result.tool_name == "cancel_restaurant_reservation":
            return "The existing reservation is cancelled."
        return super().describe(result)
