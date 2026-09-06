"""Typed contracts for the support-tool layer.

Every tool call is recorded as a :class:`ToolResult` carrying the state version it was
issued under. That single field is what makes the stale fence possible: without it,
a result arriving late is indistinguishable from a result arriving on time.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolStatus(str, Enum):
    OK = "OK"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class Subject(str, Enum):
    """What a tool call is *about*.

    Corrections invalidate subjects, not tools. When the caller says "my card isn't
    blocked, check the OTP delivery", that invalidates everything we were doing about
    ``CARD``, regardless of which specific tool happened to be in flight. Keying the
    fence on the subject rather than the tool name means a new card-related tool added
    later is fenced correctly without touching the fence.
    """

    CARD = "card"
    ONLINE_TXN = "online_txn"
    MOBILE = "mobile"
    OTP_GENERATION = "otp_generation"
    OTP_DELIVERY = "otp_delivery"
    SERVICE_HEALTH = "service_health"
    CASE = "case"


class ToolResult(BaseModel):
    """The outcome of one support-tool invocation.

    ``stale`` and ``triggered_speech`` are the two fields the acceptance suite asserts
    on. ``triggered_speech`` starts False and is only ever set True by the response
    pipeline when a result actually reaches the caller's ears, so
    ``assert stale_result.triggered_speech is False`` is a real check on real behaviour
    rather than a restatement of an intention.
    """

    model_config = ConfigDict(frozen=False)

    tool_call_id: str
    tool_name: str
    subject: Subject
    #: The state version in effect when the call was *issued*, not when it returned.
    state_version: int
    started_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    status: ToolStatus = ToolStatus.OK
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    stale: bool = False
    #: Set True only when this result's content was actually spoken to the caller.
    triggered_speech: bool = False
    #: Filled in by the fence; see resolution.stale_fence.FenceVerdict.
    fence_verdict: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at) * 1000.0

    @property
    def succeeded(self) -> bool:
        return self.status is ToolStatus.OK

    def summary(self) -> str:
        """A short, ear-friendly description used in evidence and the handoff packet."""
        if not self.succeeded:
            return f"{self.tool_name} did not complete ({self.status.value.lower()})"
        bits = ", ".join(f"{k}={v}" for k, v in self.payload.items() if not k.startswith("_"))
        return f"{self.tool_name}: {bits}" if bits else self.tool_name


class PendingToolCall(BaseModel):
    """A tool call that has been issued but has not returned yet."""

    tool_call_id: str
    tool_name: str
    subject: Subject
    state_version: int
    started_at: float = Field(default_factory=time.time)
    injected_delay_ms: int = 0

    def to_result(
        self,
        *,
        status: ToolStatus = ToolStatus.OK,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ToolResult:
        """Close out this call, preserving the *originating* state version."""
        return ToolResult(
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            subject=self.subject,
            state_version=self.state_version,
            started_at=self.started_at,
            completed_at=time.time(),
            status=status,
            payload=payload or {},
            error=error,
        )


HeardStatus = Literal["NOT_STARTED", "PARTIAL", "COMPLETED", "INTERRUPTED"]
