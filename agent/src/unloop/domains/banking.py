"""Banking OTP adapter. This preserves the original judged stress path."""

from __future__ import annotations

from typing import Any, ClassVar

from ..fixtures.loader import Fixture, LatencyTable
from ..prompts import OPENING_LINE, SYSTEM_PROMPT
from ..resolution.corrections import _DENIALS, _EVIDENCE_PATTERNS, _REDIRECTS
from ..resolution.hypotheses import Hypothesis, build_otp_hypotheses
from ..resolution.output_guard import _HYPOTHESIS_SUBJECTS
from ..resolution.state import ResolutionState
from ..tools.banking import SupportBackend
from ..tools.escalation import recommend_destination
from ..tools.types import Subject, ToolResult
from .base import DomainAdapter, ToolDefinition


class BankingAdapter(DomainAdapter):
    domain_id = "banking"
    label = "Banking"
    default_fixture = "otp_slow_tool"
    issue_type = "OTP_NOT_RECEIVED"
    issue_summary = "Debit card payment one-time password is not being received"
    opening_line = OPENING_LINE
    escalation_destination = "General banking support"
    primary_delay_tool = "get_card_status"
    tools = (
        ToolDefinition(
            "get_card_status",
            Subject.CARD,
            "check whether the card is active",
            public_name="check_card_status",
        ),
        ToolDefinition(
            "get_online_transaction_status",
            Subject.ONLINE_TXN,
            "check online payments",
            public_name="check_online_transactions",
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
    )
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
        return SYSTEM_PROMPT

    def build_hypotheses(self) -> list[Hypothesis]:
        return build_otp_hypotheses()

    def create_backend(
        self, fixture: Fixture, state: ResolutionState, latency: LatencyTable
    ) -> SupportBackend:
        return SupportBackend(fixture, state, latency=latency)

    async def invoke(
        self, backend: SupportBackend, tool_name: str, **kwargs: Any
    ) -> tuple[Any, Any]:
        customer_id = backend.fixture.customer_id
        methods = {
            "get_card_status": lambda: backend.get_card_status(customer_id),
            "get_online_transaction_status": lambda: backend.get_online_transaction_status(
                customer_id
            ),
            "get_registered_mobile_status": lambda: backend.get_registered_mobile_status(
                customer_id
            ),
            "get_otp_generation_status": lambda: backend.get_otp_generation_status(customer_id),
            "get_otp_delivery_status": lambda: backend.get_otp_delivery_status(customer_id),
            "get_service_incidents": lambda: backend.get_service_incidents(
                kwargs.get("service", "sms_provider")
            ),
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

    def describe(self, result: ToolResult) -> str:
        p = result.payload
        descriptions = {
            "get_card_status": f"The card status is {p.get('card_status', 'unknown')}.",
            "get_online_transaction_status": f"Online transactions are {p.get('online_transactions', 'unknown')}.",
            "get_registered_mobile_status": f"The registered mobile number is {p.get('registered_mobile_status', 'unknown')}.",
            "get_otp_generation_status": f"One-time password generation is {p.get('otp_generation_status', 'unknown')}.",
            "get_otp_delivery_status": f"One-time password delivery is {p.get('otp_delivery_status', 'unknown')}.",
            "get_service_incidents": f"The {p.get('service', 'service')} is {p.get('status', 'unknown')}.",
        }
        return descriptions.get(result.tool_name, super().describe(result))

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
