"""E-commerce refund-resolution adapter."""

from __future__ import annotations

from typing import ClassVar

from ..resolution.hypotheses import Hypothesis
from ..resolution.state import ResolutionState
from ..tools.types import Subject, ToolResult
from .base import COMMON_NEGATIONS, DomainAdapter, ToolDefinition, goal, rx


class EcommerceAdapter(DomainAdapter):
    domain_id = "ecommerce"
    label = "E-commerce"
    default_fixture = "ecommerce_refund_missing"
    issue_type = "REFUND_NOT_RECEIVED"
    issue_summary = "Refund is marked processed but has not reached the customer"
    opening_line = "E-commerce support. How can I help you today?"
    escalation_destination = "Refund reconciliation team"
    primary_delay_tool = "check_refund_record"
    tools = (
        ToolDefinition("list_orders", Subject.ORDER, "list the customer's synthetic orders"),
        ToolDefinition("get_order", Subject.ORDER, "get an order by full or spoken synthetic ID"),
        ToolDefinition("list_refunds", Subject.REFUND, "list the customer's synthetic refunds"),
        ToolDefinition("get_refund", Subject.REFUND, "get a refund by full or spoken synthetic ID"),
        ToolDefinition("check_refund_record", Subject.REFUND, "check the merchant refund ledger"),
        ToolDefinition(
            "trace_refund_payment",
            Subject.PAYMENT_RAIL,
            "trace the refund through the payment rail",
        ),
        ToolDefinition(
            "reissue_refund",
            Subject.REFUND,
            "reissue a stalled refund when evidence supports it",
            True,
            requires_hypothesis="PAYMENT_RAIL_DELAY",
            goal_ids=frozenset({"resolve_refund"}),
        ),
        ToolDefinition("check_order_status", Subject.ORDER, "verify the existing order status"),
        ToolDefinition(
            "cancel_order",
            Subject.ORDER,
            "cancel an eligible existing order",
            True,
            goal_ids=frozenset({"cancel_order"}),
        ),
        ToolDefinition(
            "request_return",
            Subject.ORDER,
            "open a return for an eligible delivered order",
            True,
            goal_ids=frozenset({"return_order"}),
        ),
    )
    goals = (
        goal(
            "view_refund_details",
            "Retrieve refund details such as ID, amount, or status",
            r"\b(?:what|which|how much|tell me|show|details?|id|amount|status)\b.*\brefund\b|\brefund\b.*\b(?:details?|id|amount|status|how much)\b",
            subjects=frozenset({Subject.REFUND}),
        ),
        goal(
            "view_order_details",
            "Retrieve order details such as ID, item, or status",
            r"\b(?:what|which|tell me|show|details?|id|item|status)\b.*\border\b|\border\b.*\b(?:details?|id|item|status)\b",
            subjects=frozenset({Subject.ORDER}),
        ),
        goal(
            "cancel_order",
            "Cancel an existing order",
            r"\bcancel\b.*\border\b",
            subjects=frozenset({Subject.ORDER}),
        ),
        goal(
            "return_order",
            "Return an existing order",
            r"\b(?:return|send back|wrong item|damaged)\b",
            subjects=frozenset({Subject.ORDER, Subject.REFUND}),
        ),
        goal(
            "track_order",
            "Find or verify an existing order",
            r"\b(?:track|where|status|find|verify|check)\b.*\border\b",
            subjects=frozenset({Subject.ORDER}),
        ),
        goal(
            "resolve_refund",
            "Investigate or resolve an existing refund",
            r"\b(?:refund|money back|credited)\b",
            subjects=frozenset({Subject.REFUND, Subject.PAYMENT_RAIL}),
        ),
    )
    diagnostic_goal_ids = frozenset({"resolve_refund"})
    hypothesis_subjects: ClassVar[dict[str, frozenset[Subject]]] = {
        "REFUND_ALREADY_RECEIVED": frozenset({Subject.REFUND}),
        "REFUND_NOT_SUBMITTED": frozenset({Subject.REFUND}),
        "PAYMENT_RAIL_DELAY": frozenset({Subject.PAYMENT_RAIL}),
        "REFUND_RETURNED": frozenset({Subject.REFUND, Subject.PAYMENT_RAIL}),
    }
    denial_rules = (
        (
            "REFUND_ALREADY_RECEIVED",
            rx(
                r"\b(?:refund|money)\b[^.?!]{0,35}\b(?:not|never|hasn'?t|have not)\b[^.?!]{0,25}\b(?:received|arrived|credited|reached)\b|\bstill waiting\b[^.?!]{0,30}\brefund\b"
            ),
            frozenset({Subject.REFUND}),
        ),
    )
    evidence_patterns = (
        (
            rx(r"\b(?:bank statement|account|balance)\b[^.?!]{0,30}\b(?:no|not|doesn'?t|isn'?t)\b"),
            "caller checked their account and the credit is absent",
        ),
    )
    redirects = (
        (
            rx(r"\b(?:trace|check|investigate)\b[^.?!]{0,30}\b(?:refund|payment rail|bank)\b"),
            Subject.PAYMENT_RAIL,
        ),
    )
    branch_phrases: ClassVar[dict[str, str]] = {
        "refund_record": "the merchant refund record",
        "payment_rail": "where the refund is in the payment rail",
        "refund_return": "whether the refund was returned",
    }
    remediation_actions = frozenset({"reissue_refund"})
    safety_boundary = "Resolve an existing order refund only; do not shop, recommend products, or place new orders."

    def build_hypotheses(self) -> list[Hypothesis]:
        return [
            Hypothesis(
                id="REFUND_ALREADY_RECEIVED",
                label="The processed refund has already reached the customer",
                branch="refund_record",
                assertion_patterns=[
                    rx(
                        r"\brefund\b[^.?!]{0,35}\b(?:has|was|is)\b[^.?!]{0,20}\b(?:received|credited|in your account|reached)\b"
                    )
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                id="REFUND_NOT_SUBMITTED",
                label="The merchant did not submit the refund",
                branch="refund_record",
                assertion_patterns=[
                    rx(
                        r"\brefund\b[^.?!]{0,35}\b(?:not|never|wasn'?t)\b[^.?!]{0,20}\b(?:submitted|processed|sent)\b"
                    )
                ],
                negation_cues=[rx(r"\b(?:was|is|has been)\s+(?:submitted|processed|sent)\b")],
            ),
            Hypothesis(
                id="PAYMENT_RAIL_DELAY",
                label="The refund is stalled in the payment rail",
                branch="payment_rail",
                assertion_patterns=[
                    rx(r"\brefund\b[^.?!]{0,40}\b(?:stalled|pending|delayed|held up)\b")
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
            Hypothesis(
                id="REFUND_RETURNED",
                label="The refund was returned to the merchant",
                branch="refund_return",
                assertion_patterns=[
                    rx(r"\brefund\b[^.?!]{0,30}\b(?:returned|reversed|sent back)\b")
                ],
                negation_cues=COMMON_NEGATIONS,
            ),
        ]

    async def invoke(self, backend, tool_name: str, **kwargs):
        if tool_name == "list_orders":
            return await backend.list_records(tool_name, "order")
        if tool_name == "get_order":
            return await backend.get_record(tool_name, "order", kwargs.get("order_id", ""))
        if tool_name == "list_refunds":
            return await backend.list_records(tool_name, "refund")
        if tool_name == "get_refund":
            return await backend.get_record(tool_name, "refund", kwargs.get("refund_id", ""))
        if tool_name == "check_order_status":
            return await backend.inspect_record(tool_name, "order")
        if tool_name == "check_refund_record":

            def refund_record():
                record = backend.sandbox.get_record(backend.customer_id, self.domain_id, "refund")
                return {
                    "customer_id": backend.customer_id,
                    "merchant_refund_status": record.get("processing_status", "UNKNOWN"),
                    **record,
                }

            return await backend.call(tool_name, refund_record)
        if tool_name == "trace_refund_payment":

            def refund_trace():
                record = backend.sandbox.get_record(backend.customer_id, self.domain_id, "refund")
                return {
                    "customer_id": backend.customer_id,
                    "rail_status": record.get("settlement_status", "UNKNOWN"),
                    "last_stage": "settlement",
                    **record,
                }

            return await backend.call(tool_name, refund_trace)
        if tool_name == "reissue_refund":

            def reissue():
                record = backend.sandbox.update_record(
                    backend.customer_id,
                    self.domain_id,
                    "refund",
                    {"processing_status": "REISSUED", "settlement_status": "PROCESSING"},
                    action=tool_name,
                )
                return {"customer_id": backend.customer_id, "action_status": "REISSUED", **record}

            return await backend.call(tool_name, reissue, mutates=True)
        if tool_name == "cancel_order":
            return await backend.update_record(
                tool_name, "order", {"status": "CANCELLED"}, action_status="CANCELLED"
            )
        if tool_name == "request_return":
            return await backend.update_record(
                tool_name, "order", {"return_status": "REQUESTED"}, action_status="RETURN_REQUESTED"
            )
        return await super().invoke(backend, tool_name, **kwargs)

    def absorb(self, state: ResolutionState, result: ToolResult) -> None:
        p = result.payload
        if result.tool_name == "check_refund_record":
            status = str(p.get("merchant_refund_status", "")).upper()
            state.confirm_fact("merchant_refund_status", status)
            if status == "PROCESSED":
                state.reject_hypothesis(
                    "REFUND_NOT_SUBMITTED",
                    self.evidence(
                        state,
                        result,
                        "merchant ledger shows the refund was submitted",
                        supports=False,
                    ),
                )
                state.set_strategy(
                    "investigate_payment_rail", reason="merchant processing confirmed"
                )
        elif result.tool_name == "trace_refund_payment":
            status = str(p.get("rail_status", "")).upper()
            state.confirm_fact("refund_rail_status", status, detail=dict(p))
            if status in {"STALLED", "PENDING", "DELAYED"}:
                state.support_hypothesis(
                    "PAYMENT_RAIL_DELAY",
                    self.evidence(
                        state, result, f"payment rail trace is {status.lower()}", supports=True
                    ),
                )
        elif result.tool_name == "reissue_refund":
            status = str(p.get("action_status", "")).upper()
            state.confirm_fact("refund_reissue_status", status)
            if status == "REISSUED":
                hypothesis = state.get_hypothesis("PAYMENT_RAIL_DELAY")
                if hypothesis and not hypothesis.is_rejected:
                    hypothesis.resolve(turn=state.turn)
        elif result.tool_name in {"cancel_order", "request_return"}:
            state.confirm_fact(
                "order_resolution", str(p.get("action_status", "UPDATED")), detail=dict(p)
            )

    def describe(self, result: ToolResult) -> str:
        p = result.payload
        if result.tool_name == "check_refund_record":
            return f"The merchant refund record is {p.get('merchant_refund_status', 'unknown')}; that does not prove the customer received it."
        if result.tool_name == "trace_refund_payment":
            return f"The payment rail trace is {p.get('rail_status', 'unknown')} at {p.get('last_stage', 'an unknown stage')}."
        if result.tool_name == "reissue_refund":
            return f"The corrective refund action is {p.get('action_status', 'unknown')}."
        return super().describe(result)
