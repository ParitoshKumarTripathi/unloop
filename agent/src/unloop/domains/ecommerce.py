"""E-commerce refund-resolution adapter."""

from __future__ import annotations

from typing import ClassVar

from ..resolution.hypotheses import Hypothesis
from ..resolution.state import ResolutionState
from ..tools.types import Subject, ToolResult
from .base import COMMON_NEGATIONS, DomainAdapter, ToolDefinition, rx


class EcommerceAdapter(DomainAdapter):
    domain_id = "ecommerce"
    label = "E-commerce"
    default_fixture = "ecommerce_refund_missing"
    issue_type = "REFUND_NOT_RECEIVED"
    issue_summary = "Refund is marked processed but has not reached the customer"
    opening_line = "I can help trace that refund. When were you told it had been processed?"
    escalation_destination = "Refund reconciliation team"
    primary_delay_tool = "check_refund_record"
    tools = (
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
        ),
    )
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

    def describe(self, result: ToolResult) -> str:
        p = result.payload
        if result.tool_name == "check_refund_record":
            return f"The merchant refund record is {p.get('merchant_refund_status', 'unknown')}; that does not prove the customer received it."
        if result.tool_name == "trace_refund_payment":
            return f"The payment rail trace is {p.get('rail_status', 'unknown')} at {p.get('last_stage', 'an unknown stage')}."
        if result.tool_name == "reissue_refund":
            return f"The corrective refund action is {p.get('action_status', 'unknown')}."
        return super().describe(result)
