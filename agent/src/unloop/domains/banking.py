"""Banking OTP adapter. This preserves the original judged stress path."""

from __future__ import annotations

from typing import Any, ClassVar

from ..fixtures.loader import Fixture, LatencyTable
from ..prompts import SYSTEM_PROMPT
from ..resolution.corrections import _DENIALS, _EVIDENCE_PATTERNS, _REDIRECTS
from ..resolution.hypotheses import Hypothesis, build_otp_hypotheses
from ..resolution.output_guard import _HYPOTHESIS_SUBJECTS
from ..resolution.state import ResolutionState
from ..sandbox import SyntheticSupportSandbox
from ..tools.banking import SupportBackend
from ..tools.escalation import recommend_destination
from ..tools.types import Subject, ToolResult
from .base import DomainAdapter, ToolDefinition, goal


class BankingAdapter(DomainAdapter):
    domain_id = "banking"
    label = "Banking"
    default_fixture = "otp_slow_tool"
    issue_type = "OTP_NOT_RECEIVED"
    issue_summary = "Debit card payment one-time password is not being received"
    opening_line = "Banking support. How can I help you today?"
    escalation_destination = "General banking support"
    primary_delay_tool = "get_card_status"
    tools = (
        ToolDefinition(
            "get_card_status",
            Subject.CARD,
            "retrieve the synthetic card ID, safe last four digits, and card status",
            public_name="check_card_status",
        ),
        ToolDefinition(
            "get_online_transaction_status",
            Subject.ONLINE_TXN,
            "check online payments",
            public_name="check_online_transactions",
        ),
        ToolDefinition(
            "list_recent_transactions",
            Subject.TRANSACTION,
            "list recent synthetic transactions when the customer asks about transaction history or their latest payment",
        ),
        ToolDefinition(
            "get_transaction",
            Subject.TRANSACTION,
            "look up a synthetic transaction by ID, including a spoken numeric ID such as five zero one",
        ),
        ToolDefinition(
            "get_registered_mobile_status",
            Subject.MOBILE,
            "check number verification",
            public_name="check_registered_mobile",
        ),
        ToolDefinition(
            "get_otp_generation_status",
            Subject.OTP_GENERATION,
            "check OTP generation",
            public_name="check_otp_generation",
        ),
        ToolDefinition(
            "get_otp_delivery_status",
            Subject.OTP_DELIVERY,
            "check SMS delivery",
            public_name="check_otp_delivery",
        ),
        ToolDefinition(
            "get_service_incidents",
            Subject.SERVICE_HEALTH,
            "check service incidents",
            public_name="check_service_incidents",
        ),
        ToolDefinition(
            "resend_otp",
            Subject.OTP_DELIVERY,
            "resend the one-time password after a delivery failure is confirmed",
            True,
            requires_hypothesis="OTP_DELIVERY_FAILED",
            goal_ids=frozenset({"resolve_otp"}),
        ),
    )
    goals = (
        goal(
            "view_card_details",
            "Retrieve safe synthetic card details",
            r"\b(?:what|which|tell me|show|details?|id|last four|ending)\b.*\b(?:card|digits?)\b|\bcard\b.*\b(?:details?|id|last four|ending)\b",
            subjects=frozenset({Subject.CARD}),
        ),
        goal(
            "view_otp_event_details",
            "Retrieve synthetic OTP event details",
            r"\b(?:what|which|tell me|show|details?|id|status)\b.*\b(?:otp|one[- ]time password|code)\b",
            subjects=frozenset({Subject.OTP_GENERATION, Subject.OTP_DELIVERY}),
        ),
        goal(
            "resolve_otp",
            "Resolve a one-time-password delivery problem",
            r"\b(?:otp|one[- ]time password|code)\b",
            subjects=frozenset(
                {
                    Subject.CARD,
                    Subject.ONLINE_TXN,
                    Subject.MOBILE,
                    Subject.OTP_GENERATION,
                    Subject.OTP_DELIVERY,
                    Subject.SERVICE_HEALTH,
                }
            ),
        ),
        goal(
            "review_transactions",
            "Review recent transactions or look up a transaction by ID",
            r"\b(?:transaction|transactions|payment|payments|charge|charges|purchase|purchases)\b.*\b(?:last|latest|recent|history|status|details?|id|find|look\s*up|check)\b",
            r"\b(?:last|latest|recent|history|find|look\s*up|check)\b.*\b(?:transaction|transactions|payment|payments|charge|charges|purchase|purchases)\b",
            subjects=frozenset({Subject.TRANSACTION}),
        ),
        goal(
            "verify_card",
            "Verify card status and payment eligibility",
            r"\b(?:card|debit card)\b.*\b(?:status|blocked|active|working|payment)\b",
            subjects=frozenset({Subject.CARD, Subject.ONLINE_TXN}),
        ),
        goal(
            "verify_registered_mobile",
            "Verify the registered mobile status",
            r"\b(?:registered mobile|phone number|mobile number)\b",
            subjects=frozenset({Subject.MOBILE}),
        ),
        goal(
            "manage_card_security",
            "Escalate a card block, freeze, or replacement request",
            r"\b(?:block|freeze|lock|replace)\b.*\b(?:card|debit card)\b|\b(?:card|debit card)\b.*\b(?:block|freeze|lock|replacement)\b",
            subjects=frozenset({Subject.CARD, Subject.CASE}),
        ),
    )
    diagnostic_goal_ids = frozenset({"resolve_otp"})
    escalation_goal_ids = frozenset({"manage_card_security"})
    hypothesis_subjects = _HYPOTHESIS_SUBJECTS
    denial_rules = _DENIALS
    evidence_patterns = _EVIDENCE_PATTERNS
    redirects = _REDIRECTS
    branch_phrases: ClassVar[dict[str, str]] = {
        "card": "the card status",
        "online_txn": "whether online payments are switched on",
        "contact": "the mobile number we have on file",
        "otp_generation": "whether the one-time password was generated",
        "otp_delivery": "whether the message was delivered",
    }
    remediation_actions = frozenset(
        {"resend_otp", "retry_otp_delivery", "reset_online_transactions"}
    )
    safety_boundary = "Provide account support only; do not give financial advice."

    def instructions(self) -> str:
        tool_lines = "\n".join(f"- {tool.exposed_name}: {tool.purpose}" for tool in self.all_tools)
        goal_lines = "\n".join(f"- {item.id}: {item.label}" for item in self.goals)
        return f"""{SYSTEM_PROMPT}

# Mutable support goal
The demo preset only seeds synthetic account data. It is not the customer's goal.
Infer the current support goal from the customer's latest words. If they change their
mind, immediately follow the new goal and stop pursuing the old one.

# Available support operations
{tool_lines}

# Supported customer goals
{goal_lines}
"""

    def build_hypotheses(self) -> list[Hypothesis]:
        return build_otp_hypotheses()

    def create_backend(
        self,
        fixture: Fixture,
        state: ResolutionState,
        latency: LatencyTable,
        sandbox: SyntheticSupportSandbox | None = None,
    ) -> SupportBackend:
        return SupportBackend(fixture, state, latency=latency, sandbox=sandbox)

    async def invoke(
        self, backend: SupportBackend, tool_name: str, **kwargs: Any
    ) -> tuple[Any, Any]:
        if tool_name == "lookup_customer":
            return await super().invoke(backend, tool_name, **kwargs)
        customer_id = backend.customer_id
        methods = {
            "get_card_status": lambda: backend.get_card_status(customer_id),
            "get_online_transaction_status": lambda: backend.get_online_transaction_status(
                customer_id
            ),
            "list_recent_transactions": lambda: backend.list_recent_transactions(
                customer_id, kwargs.get("limit", 5)
            ),
            "get_transaction": lambda: backend.get_transaction(
                customer_id, str(kwargs.get("transaction_id", ""))
            ),
            "get_registered_mobile_status": lambda: backend.get_registered_mobile_status(
                customer_id
            ),
            "get_otp_generation_status": lambda: backend.get_otp_generation_status(customer_id),
            "get_otp_delivery_status": lambda: backend.get_otp_delivery_status(customer_id),
            "get_service_incidents": lambda: backend.get_service_incidents(
                kwargs.get("service", "sms_provider")
            ),
            "resend_otp": lambda: backend.resend_otp(customer_id),
        }
        return await methods[tool_name]()

    def absorb(self, state: ResolutionState, result: ToolResult) -> None:
        payload = result.payload
        tool_name = result.tool_name
        if tool_name == "get_card_status":
            status = str(payload.get("card_status", "")).upper()
            state.confirm_fact("card_status", status)
            if status == "ACTIVE":
                state.reject_hypothesis(
                    "CARD_BLOCKED",
                    self.evidence(
                        state, result, "backend reports the card is active", supports=False
                    ),
                )
            elif status:
                state.support_hypothesis(
                    "CARD_BLOCKED",
                    self.evidence(
                        state, result, f"backend reports card status {status}", supports=True
                    ),
                )
        elif tool_name == "get_online_transaction_status":
            status = str(payload.get("online_transactions", "")).upper()
            state.confirm_fact("online_transactions", status)
            target = "ONLINE_TXN_DISABLED"
            if status == "ENABLED":
                state.reject_hypothesis(
                    target,
                    self.evidence(state, result, "online payments are enabled", supports=False),
                )
            elif status:
                state.support_hypothesis(
                    target,
                    self.evidence(state, result, f"online payments are {status}", supports=True),
                )
        elif tool_name == "list_recent_transactions":
            transactions = payload.get("transactions", [])
            state.confirm_fact(
                "recent_transactions",
                str(payload.get("count", len(transactions))),
                detail={"transactions": transactions},
            )
        elif tool_name == "get_transaction":
            transaction_id = str(
                payload.get("transaction_id") or payload.get("requested_transaction_id", "")
            )
            state.confirm_fact(
                f"transaction_{transaction_id or 'lookup'}",
                "FOUND" if payload.get("found") else "NOT_FOUND",
                detail=dict(payload),
            )
        elif tool_name == "get_registered_mobile_status":
            status = str(payload.get("registered_mobile_status", "")).upper()
            state.confirm_fact("registered_mobile_status", status)
            target = "MOBILE_NOT_REGISTERED"
            if status == "VERIFIED":
                state.reject_hypothesis(
                    target,
                    self.evidence(state, result, "registered number is verified", supports=False),
                )
            elif status:
                state.support_hypothesis(
                    target,
                    self.evidence(state, result, f"number status is {status}", supports=True),
                )
        elif tool_name == "get_otp_generation_status":
            status = str(payload.get("otp_generation_status", "")).upper()
            state.confirm_fact("otp_generation_status", status)
            target = "OTP_NOT_GENERATED"
            if status == "SUCCESS":
                state.reject_hypothesis(
                    target, self.evidence(state, result, "the OTP was generated", supports=False)
                )
            elif status:
                state.support_hypothesis(
                    target,
                    self.evidence(state, result, f"OTP generation is {status}", supports=True),
                )
        elif tool_name == "get_otp_delivery_status":
            status = str(payload.get("otp_delivery_status", "")).upper()
            reason = str(payload.get("otp_delivery_failure_reason") or "")
            state.confirm_fact("otp_delivery_status", status, detail={"reason": reason})
            target = "OTP_DELIVERY_FAILED"
            if status == "FAILED":
                state.support_hypothesis(
                    target,
                    self.evidence(
                        state, result, f"delivery failed: {reason}".rstrip(": "), supports=True
                    ),
                )
                state.set_strategy("investigate_otp_delivery", reason="delivery failure confirmed")
            elif status:
                state.reject_hypothesis(
                    target, self.evidence(state, result, f"delivery is {status}", supports=False)
                )
        elif tool_name == "get_service_incidents":
            status = str(payload.get("status", "")).upper()
            service = str(payload.get("service", ""))
            state.confirm_fact(f"incident_{service}", status, detail=dict(payload))
            if service == "sms_provider" and status in {"DEGRADED", "OUTAGE", "DOWN"}:
                state.support_hypothesis(
                    "SMS_PROVIDER_INCIDENT",
                    self.evidence(state, result, f"message provider is {status}", supports=True),
                )
        elif tool_name == "resend_otp":
            state.confirm_fact("otp_resend_status", str(payload.get("action_status", "UNKNOWN")))
            hypothesis = state.get_hypothesis("OTP_DELIVERY_FAILED")
            if hypothesis and not hypothesis.is_rejected:
                hypothesis.resolve(turn=state.turn)

    def describe(self, result: ToolResult) -> str:
        p = result.payload
        descriptions = {
            "get_card_status": (
                f"Synthetic card {p.get('card_id', 'unknown')} ending in "
                f"{p.get('card_last4', 'unknown')} is {p.get('card_status', 'unknown')}."
            ),
            "get_online_transaction_status": f"Online transactions are {p.get('online_transactions', 'unknown')}.",
            "list_recent_transactions": self._describe_transactions(p),
            "get_transaction": self._describe_transaction(p),
            "get_registered_mobile_status": f"The registered mobile number is {p.get('registered_mobile_status', 'unknown')}.",
            "get_otp_generation_status": (
                f"OTP event {p.get('otp_event_id', 'unknown')} for transaction "
                f"{p.get('transaction_id', 'unknown')} has generation status "
                f"{p.get('otp_generation_status', 'unknown')}."
            ),
            "get_otp_delivery_status": (
                f"OTP event {p.get('otp_event_id', 'unknown')} for transaction "
                f"{p.get('transaction_id', 'unknown')} has delivery status "
                f"{p.get('otp_delivery_status', 'unknown')}."
            ),
            "get_service_incidents": f"The {p.get('service', 'service')} is {p.get('status', 'unknown')}.",
            "resend_otp": f"The one-time password was {p.get('action_status', 'not resent').lower()} and delivery is {p.get('otp_delivery_status', 'unknown').lower()}.",
        }
        return descriptions.get(result.tool_name, super().describe(result))

    @staticmethod
    def _describe_transaction(payload: dict[str, Any]) -> str:
        if not payload.get("found"):
            return f"No synthetic transaction matched {payload.get('requested_transaction_id', 'that ID')}."
        return (
            f"Transaction {payload.get('transaction_id')} at {payload.get('merchant')} "
            f"was for {payload.get('amount')} and its status is {payload.get('status')}."
        )

    @classmethod
    def _describe_transactions(cls, payload: dict[str, Any]) -> str:
        transactions = payload.get("transactions") or []
        if not transactions:
            return "No recent synthetic transactions were found."
        return "Recent synthetic transactions: " + " ".join(
            cls._describe_transaction({"found": True, **item}) for item in transactions
        )

    def recommend_destination(self, state: ResolutionState) -> str:
        return recommend_destination(state)

    def conflict(self, state: ResolutionState, hypothesis_id: str) -> str | None:
        if hypothesis_id != "CARD_BLOCKED":
            return None
        result = state.latest_result_for(Subject.CARD)
        if result is None:
            return None
        status = str(result.payload.get("card_status", "")).upper()
        if status and status != "ACTIVE":
            return f"backend reports card_status={status} while caller reports the card works"
        return None
