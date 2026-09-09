"""Contract between the reusable resolution engine and a support domain."""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from ..fixtures.loader import Fixture, LatencyTable
from ..resolution.goals import GoalDefinition
from ..resolution.hypotheses import Evidence, EvidenceSource, Hypothesis
from ..resolution.state import ResolutionState
from ..sandbox import SyntheticSupportSandbox
from ..tools.support import FixtureSupportBackend, SupportToolError
from ..tools.types import Subject, ToolResult


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    subject: Subject
    purpose: str
    corrective_action: bool = False
    public_name: str | None = None
    requires_hypothesis: str | None = None
    goal_ids: frozenset[str] = frozenset()

    @property
    def exposed_name(self) -> str:
        return self.public_name or self.name


def rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def goal(
    goal_id: str,
    label: str,
    *patterns: str,
    subjects: frozenset[Subject],
    tools: frozenset[str] = frozenset(),
) -> GoalDefinition:
    return GoalDefinition(
        goal_id, label, tuple(rx(pattern) for pattern in patterns), subjects, tools
    )


COMMON_NEGATIONS = [
    rx(r"\b(not|n't|no longer|isn'?t|aren'?t|doesn'?t|don'?t|wasn'?t)\b"),
    rx(r"\b(rule[sd]? out|ruling out|ruled out|not the (?:issue|problem|cause))\b"),
    rx(r"\b(correct|active|confirmed|working|fine|okay|ok|exists?)\b"),
]


class DomainAdapter(ABC):
    """Domain knowledge only; all lifecycle and safety behavior stays in the engine."""

    domain_id: str
    label: str
    default_fixture: str
    issue_type: str
    issue_summary: str
    opening_line: str
    escalation_destination: str
    primary_delay_tool: str
    tools: tuple[ToolDefinition, ...]
    goals: tuple[GoalDefinition, ...] = ()
    diagnostic_goal_ids: frozenset[str] = frozenset()
    hypothesis_subjects: dict[str, frozenset[Subject]]
    denial_rules: tuple[tuple[str, re.Pattern[str], frozenset[Subject]], ...] = ()
    evidence_patterns: tuple[tuple[re.Pattern[str], str], ...] = ()
    redirects: tuple[tuple[re.Pattern[str], Subject], ...] = ()
    branch_phrases: ClassVar[dict[str, str]] = {}
    remediation_actions: frozenset[str] = frozenset()
    safety_boundary: str = "Resolve the existing support case only."

    @property
    def all_tools(self) -> tuple[ToolDefinition, ...]:
        return (
            ToolDefinition(
                "lookup_customer", Subject.CASE, "verify the synthetic authenticated customer"
            ),
            *self.tools,
        )

    @abstractmethod
    def build_hypotheses(self) -> list[Hypothesis]:
        raise NotImplementedError

    def create_backend(
        self,
        fixture: Fixture,
        state: ResolutionState,
        latency: LatencyTable,
        sandbox: SyntheticSupportSandbox | None = None,
    ) -> FixtureSupportBackend:
        subjects = {tool.name: tool.subject for tool in self.all_tools}
        subjects.update({"create_support_case": Subject.CASE, "escalate_to_human": Subject.CASE})
        return FixtureSupportBackend(fixture, state, subjects, latency=latency, sandbox=sandbox)

    async def invoke(
        self, backend: FixtureSupportBackend, tool_name: str, **kwargs: Any
    ) -> tuple[Any, Any]:
        if tool_name == "lookup_customer":
            return await backend.call(
                tool_name,
                lambda: (
                    backend.sandbox.resolve_synthetic_identity(
                        str(kwargs.get("identifier") or backend.customer_id)
                    )
                    or {}
                ),
            )
        raise SupportToolError(
            f"{self.domain_id} adapter has no sandbox operation for {tool_name!r}"
        )

    @abstractmethod
    def absorb(self, state: ResolutionState, result: ToolResult) -> None:
        raise NotImplementedError

    def describe(self, result: ToolResult) -> str:
        parts = [
            f"{key.replace('_', ' ')} is {value}"
            for key, value in result.payload.items()
            if key != "customer_id" and value not in (None, "")
        ]
        return ("; ".join(parts) or "The check completed") + "."

    def recommend_destination(self, _state: ResolutionState) -> str:
        return self.escalation_destination

    def conflict(self, _state: ResolutionState, _hypothesis_id: str) -> str | None:
        return None

    def evidence(
        self,
        state: ResolutionState,
        result: ToolResult,
        summary: str,
        *,
        supports: bool,
    ) -> Evidence:
        return Evidence(
            id=f"ev_{result.tool_name}_{state.state_version}_{uuid.uuid4().hex[:6]}",
            source=EvidenceSource.TOOL,
            summary=summary,
            observed_at_version=state.state_version,
            supports=supports,
            detail=dict(result.payload),
        )

    def instructions(self) -> str:
        tool_lines = "\n".join(f"- {tool.exposed_name}: {tool.purpose}" for tool in self.all_tools)
        goal_lines = "\n".join(f"- {goal.id}: {goal.label}" for goal in self.goals)
        return f"""You are an AI voice customer-support resolution agent for {self.label.lower()}.
The selected demo preset only seeds synthetic records. It is not the customer's goal.
Infer the current support goal from the customer's latest words. If they change their mind,
immediately follow the new goal and stop pursuing the old one.
Investigate records, accept customer corrections, change strategy when an explanation is wrong,
take a corrective action when the evidence supports it, and escalate with full context otherwise.

# Voice style
- Speak in plain prose, one to three short sentences, with one question at a time.
- Never use markdown, lists, internal tool names, state versions, or confidence scores in speech.
- Check before asserting. If a check fails, say you could not verify it. Never guess.
- Do not ask whether it is resolved unless a corrective action or escalation actually occurred.

# Corrections and loops
- Treat a customer's explicit correction as evidence and do not repeat a rejected cause.
- Change the check, not merely the wording. If no useful branch remains, escalate.
- Acknowledge a correction once and move forward.

# Scope
- {self.safety_boundary}
- All records here are synthetic demo data. Never request passwords, payment credentials, or codes.

# Available support operations
{tool_lines}

# Supported customer goals
{goal_lines}
"""
