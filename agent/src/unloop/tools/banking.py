"""Deterministic mock support backend.

These are the "bank systems" UNLOOP queries. They are synthetic, they are seeded
entirely from a fixture file, and they support injected latency and injected failure
so the stress case can be reproduced exactly rather than waited for.

Every call goes through :meth:`SupportBackend.call`, which:

* registers the call against the **current** state version (this is what later makes
  staleness detectable),
* awaits any injected delay,
* runs the fixture-backed handler,
* passes the result through the stale fence,
* records it.

The tools never mutate the caller's belief directly. They return evidence; the
resolution engine decides what it means.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from ..fixtures.loader import Fixture, LatencyTable
from ..observability.events import EventType
from ..resolution.stale_fence import FenceDecision, StaleFence
from ..resolution.state import ResolutionState
from ..sandbox import DEMO_CUSTOMER_ID, SyntheticSupportSandbox
from .types import Subject, ToolResult, ToolStatus


class ToolError(RuntimeError):
    """A backend failure the agent must communicate rather than paper over."""


#: Which subject each tool reports on. The stale fence keys off this, not the name.
TOOL_SUBJECTS: dict[str, Subject] = {
    "get_card_status": Subject.CARD,
    "get_online_transaction_status": Subject.ONLINE_TXN,
    "get_registered_mobile_status": Subject.MOBILE,
    "get_otp_generation_status": Subject.OTP_GENERATION,
    "get_otp_delivery_status": Subject.OTP_DELIVERY,
    "get_service_incidents": Subject.SERVICE_HEALTH,
    "resend_otp": Subject.OTP_DELIVERY,
    "create_support_case": Subject.CASE,
    "escalate_to_human": Subject.CASE,
}


class SupportBackend:
    """Fixture-backed mock of the bank's internal APIs."""

    def __init__(
        self,
        fixture: Fixture,
        state: ResolutionState,
        *,
        latency: LatencyTable | None = None,
        sandbox: SyntheticSupportSandbox | None = None,
    ) -> None:
        self.fixture = fixture
        self.state = state
        self.latency = latency or LatencyTable(fixture.tool_delays_ms)
        self.fence = StaleFence(state)
        self.sandbox = sandbox or SyntheticSupportSandbox()
        self.customer_id = DEMO_CUSTOMER_ID
        self._case_counter = 0

    # -- infrastructure ------------------------------------------------------

    async def call(
        self,
        tool_name: str,
        handler: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]],
        *,
        mutates: bool = False,
    ) -> tuple[ToolResult, FenceDecision]:
        """Run one tool call end to end, fenced.

        Returns the result *and* the fence decision. Callers must consult the
        decision before speaking: a ``SUPERSEDED`` result is real data about a
        question that no longer matters, and saying it out loud is the bug.
        """
        subject = TOOL_SUBJECTS.get(tool_name, Subject.CASE)
        call_id = f"tc_{uuid.uuid4().hex[:10]}"
        delay_ms = self.latency.get(tool_name)

        # Registered *before* the await, so the originating version is the version
        # that was current when we decided to ask — not whatever it becomes later.
        pending = self.state.start_tool(
            tool_call_id=call_id,
            tool_name=tool_name,
            subject=subject,
            injected_delay_ms=delay_ms,
        )

        if delay_ms:
            await asyncio.sleep(delay_ms / 1000.0)

        forced_failure = self.fixture.tool_failures.get(tool_name)
        if forced_failure:
            status = ToolStatus.TIMEOUT if forced_failure.upper() == "TIMEOUT" else ToolStatus.ERROR
            result = pending.to_result(
                status=status,
                error=f"{tool_name} did not respond ({forced_failure})",
            )
        else:
            try:
                if mutates:
                    probe = pending.to_result(payload={"action_status": "NOT_APPLIED"})
                    decision = self.fence.evaluate_tool(probe)
                    if not decision.may_speak:
                        self.state.complete_tool(probe)
                        return probe, decision
                payload = handler()
                if asyncio.iscoroutine(payload):
                    payload = await payload
                result = pending.to_result(payload=dict(payload))
            except Exception as exc:
                result = pending.to_result(status=ToolStatus.ERROR, error=str(exc))

        decision = self.fence.evaluate_tool(result)
        self.state.complete_tool(result)
        return result, decision

    # -- the tools -----------------------------------------------------------

    async def get_card_status(self, customer_id: str) -> tuple[ToolResult, FenceDecision]:
        """Whether the debit card is active, blocked or restricted."""

        def handler() -> dict[str, Any]:
            backend = self.sandbox.get_record(DEMO_CUSTOMER_ID, "banking", "card") or {}
            return {
                "customer_id": customer_id,
                "card_last4": backend.get("last4", "4821"),
                "card_status": backend.get("status", "ACTIVE"),
            }

        return await self.call("get_card_status", handler)

    async def get_online_transaction_status(
        self, customer_id: str
    ) -> tuple[ToolResult, FenceDecision]:
        """Whether online/e-commerce use is switched on for the card."""

        def handler() -> dict[str, Any]:
            return {
                "customer_id": customer_id,
                "online_transactions": (
                    self.sandbox.get_record(DEMO_CUSTOMER_ID, "banking", "card") or {}
                ).get("online_transactions", "ENABLED"),
            }

        return await self.call("get_online_transaction_status", handler)

    async def get_registered_mobile_status(
        self, customer_id: str
    ) -> tuple[ToolResult, FenceDecision]:
        """Whether the mobile number on file is verified.

        Returns only the verification *status*. The number itself is never fetched,
        logged, or spoken — there is nothing the agent needs it for, and not having
        it is cheaper than redacting it everywhere later.
        """

        def handler() -> dict[str, Any]:
            return {
                "customer_id": customer_id,
                "registered_mobile_status": (
                    self.sandbox.get_record(DEMO_CUSTOMER_ID, "banking", "card") or {}
                ).get("registered_mobile_status", "VERIFIED"),
            }

        return await self.call("get_registered_mobile_status", handler)

    async def get_otp_generation_status(self, customer_id: str) -> tuple[ToolResult, FenceDecision]:
        """Whether the bank actually minted an OTP for the attempted payment."""

        def handler() -> dict[str, Any]:
            return {
                "customer_id": customer_id,
                "otp_generation_status": (
                    self.sandbox.get_record(DEMO_CUSTOMER_ID, "banking", "otp") or {}
                ).get("generation_status", "SUCCESS"),
            }

        return await self.call("get_otp_generation_status", handler)

    async def get_otp_delivery_status(self, customer_id: str) -> tuple[ToolResult, FenceDecision]:
        """Whether the generated OTP was successfully delivered by SMS."""

        def handler() -> dict[str, Any]:
            backend = self.sandbox.get_record(DEMO_CUSTOMER_ID, "banking", "otp") or {}
            return {
                "customer_id": customer_id,
                "otp_delivery_status": backend.get("delivery_status", "FAILED"),
                "otp_delivery_failure_reason": backend.get("failure_reason"),
            }

        return await self.call("get_otp_delivery_status", handler)

    async def get_service_incidents(self, service: str) -> tuple[ToolResult, FenceDecision]:
        """Known incidents for a downstream service, e.g. ``sms_provider``."""

        def handler() -> dict[str, Any]:
            entry = self.sandbox.find_record(
                DEMO_CUSTOMER_ID, "banking", "service", "service", service
            )
            if entry is None:
                return {
                    "service": service,
                    "status": "UNKNOWN",
                    "summary": "No data for that service",
                }
            return {"service": service, **entry}

        return await self.call("get_service_incidents", handler)

    async def resend_otp(self, customer_id: str) -> tuple[ToolResult, FenceDecision]:
        """Synthetic corrective resend after delivery failure has been confirmed."""

        def handler() -> dict[str, Any]:
            self.sandbox.update_record(
                DEMO_CUSTOMER_ID,
                "banking",
                "otp",
                {"delivery_status": "DELIVERED", "failure_reason": None},
                action="resend_otp",
            )
            return {
                "customer_id": customer_id,
                "action_status": "RESENT",
                "otp_delivery_status": "DELIVERED",
            }

        return await self.call("resend_otp", handler, mutates=True)

    async def create_support_case(
        self, customer_id: str, summary: str, evidence: dict[str, Any]
    ) -> tuple[ToolResult, FenceDecision]:
        """Open a case carrying the structured resolution state."""

        def handler() -> dict[str, Any]:
            self._case_counter += 1
            case_id = f"CASE-{self.fixture.card_last4}-{self._case_counter:03d}"
            self.state.case_id = case_id
            return {
                "case_id": case_id,
                "customer_id": customer_id,
                "summary": summary,
                "evidence_keys": sorted(evidence.keys()),
            }

        return await self.call("create_support_case", handler)

    async def escalate_to_human(
        self, case_id: str, handoff_packet: dict[str, Any]
    ) -> tuple[ToolResult, FenceDecision]:
        """Route the case to a human queue with the full context packet."""

        def handler() -> dict[str, Any]:
            destination = handoff_packet.get("recommended_destination", "General support")
            self.state.recorder.emit(
                EventType.ESCALATION_CREATED,
                state_version=self.state.state_version,
                case_id=case_id,
                destination=destination,
                confirmed_count=len(handoff_packet.get("confirmed", [])),
                rejected_count=len(handoff_packet.get("rejected", [])),
            )
            return {
                "case_id": case_id,
                "routed_to": destination,
                "packet_sections": sorted(handoff_packet.keys()),
            }

        return await self.call("escalate_to_human", handler)

    # -- debugging control ---------------------------------------------------

    def set_mock_tool_delay(self, tool_name: str, milliseconds: int) -> int:
        """Inject latency into one tool. Used by the demo panel and the test harness.

        This is a fixture condition, not a script: it changes *when* a real result
        arrives, never *what* it says.
        """
        if tool_name not in TOOL_SUBJECTS:
            raise ToolError(f"unknown tool {tool_name!r}")
        applied = self.latency.set(tool_name, milliseconds)
        self.state.recorder.emit(
            EventType.MOCK_DELAY_SET,
            state_version=self.state.state_version,
            tool_name=tool_name,
            delay_ms=applied,
            requested_ms=int(milliseconds),
        )
        return applied
