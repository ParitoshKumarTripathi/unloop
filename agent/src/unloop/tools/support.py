"""Shared fixture-backed tool transport for non-banking domain adapters.

This module contains the version stamping, latency injection, failure injection, stale
fencing, and case handoff plumbing. Domain adapters only declare subjects and fixture
payloads; they do not get their own copy of resolution mechanics.
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
from .types import Subject, ToolResult, ToolStatus


class SupportToolError(RuntimeError):
    pass


class FixtureSupportBackend:
    """One shared execution path for every fixture-defined support tool."""

    def __init__(
        self,
        fixture: Fixture,
        state: ResolutionState,
        tool_subjects: dict[str, Subject],
        *,
        latency: LatencyTable | None = None,
    ) -> None:
        self.fixture = fixture
        self.state = state
        self.tool_subjects = dict(tool_subjects)
        self.latency = latency or LatencyTable(fixture.tool_delays_ms)
        self.fence = StaleFence(state)
        self._case_counter = 0

    async def call(
        self,
        tool_name: str,
        handler: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]],
    ) -> tuple[ToolResult, FenceDecision]:
        subject = self.tool_subjects.get(tool_name, Subject.CASE)
        call_id = f"tc_{uuid.uuid4().hex[:10]}"
        delay_ms = self.latency.get(tool_name)
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
                payload = handler()
                if asyncio.iscoroutine(payload):
                    payload = await payload
                result = pending.to_result(payload=dict(payload))
            except Exception as exc:
                result = pending.to_result(status=ToolStatus.ERROR, error=str(exc))

        decision = self.fence.evaluate_tool(result)
        self.state.complete_tool(result)
        return result, decision

    async def run_fixture_tool(self, tool_name: str) -> tuple[ToolResult, FenceDecision]:
        if tool_name not in self.tool_subjects:
            raise SupportToolError(f"unknown tool {tool_name!r}")

        def handler() -> dict[str, Any]:
            payloads = self.fixture.backend_state.get("tool_results", {})
            payload = payloads.get(tool_name)
            if payload is None:
                raise SupportToolError(f"fixture has no payload for {tool_name!r}")
            return {"customer_id": self.fixture.customer_id, **dict(payload)}

        return await self.call(tool_name, handler)

    async def create_support_case(
        self, customer_id: str, summary: str, evidence: dict[str, Any]
    ) -> tuple[ToolResult, FenceDecision]:
        def handler() -> dict[str, Any]:
            self._case_counter += 1
            prefix = self.fixture.domain[:4].upper()
            case_id = f"{prefix}-{self._case_counter:03d}"
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
            return {"case_id": case_id, "routed_to": destination}

        return await self.call("escalate_to_human", handler)

    def set_mock_tool_delay(self, tool_name: str, milliseconds: int) -> int:
        if tool_name not in self.tool_subjects:
            raise SupportToolError(f"unknown tool {tool_name!r}")
        applied = self.latency.set(tool_name, milliseconds)
        self.state.recorder.emit(
            EventType.MOCK_DELAY_SET,
            state_version=self.state.state_version,
            tool_name=tool_name,
            delay_ms=applied,
            requested_ms=int(milliseconds),
        )
        return applied
