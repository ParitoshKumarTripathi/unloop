"""Deterministic scenario harness.

One code path, two consumers: ``pytest`` asserts on it, and
``scripts/generate_evidence.py`` measures it. That is deliberate — if the evidence
script had its own copy of the scenario, the published numbers could describe
something the tests never checked.

What this harness does and does not cover:

* **Does** cover the full resolution engine on real fixtures — tool dispatch with
  real injected latency, correction extraction, hypothesis rejection, the stale
  fence, the output guard, loop detection, and the handoff packet.
* **Does not** cover audio. There is no LiveKit session, no microphone, no Rime
  socket. Timings it reports are in-process engine timings, and they are labelled as
  such. Anything requiring live media — interruption-to-audio-stop, Rime
  time-to-first-audio — is reported as unmeasured rather than estimated.

That boundary is drawn in the data, not just in prose: see ``RunOutcome.measured``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .fixtures.loader import load_fixture
from .observability.events import EventRecorder, EventType
from .resolution.corrections import CorrectionExtractor, CorrectionReconciler
from .resolution.hypotheses import HypothesisStatus, build_otp_hypotheses
from .resolution.loop_detector import LoopDetector
from .resolution.output_guard import OutputGuard
from .resolution.stale_fence import SpeechTicket, StaleFence
from .resolution.state import ResolutionState, SpeechRecord
from .tools.banking import SupportBackend
from .tools.escalation import build_handoff_packet
from .tools.types import ToolResult

#: The caller's correction in the primary stress case, verbatim from the brief.
CORRECTION_UTTERANCE = (
    "No, my card is not blocked. I used it five minutes ago. Check the OTP delivery."
)

#: What a naive agent says first, and what it must never say again afterwards.
NAIVE_DIAGNOSIS = "It looks like your card is blocked, which would stop the one-time password."


@dataclass
class RunOutcome:
    """The result of one scenario run."""

    scenario: str
    run_index: int
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    #: In-process engine timings, in milliseconds. These are real measurements of
    #: real code, but they are NOT end-to-end audio latencies.
    measured: dict[str, float] = field(default_factory=dict)
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "run_index": self.run_index,
            "passed": self.passed,
            "checks": self.checks,
            "failures": self.failures,
            "measured_ms": self.measured,
        }


class ScenarioHarness:
    """Builds and runs one deterministic scenario end to end."""

    def __init__(self, fixture_id: str, *, session_id: str | None = None) -> None:
        self.fixture = load_fixture(fixture_id)
        self.state = ResolutionState(
            session_id=session_id or f"harness_{uuid.uuid4().hex[:10]}",
            recorder=EventRecorder(session_id or f"harness_{uuid.uuid4().hex[:10]}"),
            issue_type="OTP_NOT_RECEIVED",
            issue_summary="Debit card payment one-time password is not being received",
            hypotheses=build_otp_hypotheses(),
        )
        self.backend = SupportBackend(self.fixture, self.state)
        self.fence = StaleFence(self.state)
        self.guard = OutputGuard(self.state)
        self.loop_detector = LoopDetector(self.state)
        self.extractor = CorrectionExtractor()
        self.reconciler = CorrectionReconciler(self.state)

    # -- conversation primitives --------------------------------------------

    def agent_says(
        self, text: str, *, speech_id: str | None = None
    ) -> tuple[bool, SpeechRecord | None]:
        """Attempt an agent turn. Returns (was_spoken, record).

        Runs the same gate the live agent runs: the output guard, then the speech
        fence. A blocked turn produces no ``SpeechRecord`` marked heard, which is what
        makes "the caller never heard the contradicted diagnosis" checkable.
        """
        speech_id = speech_id or f"sp_{uuid.uuid4().hex[:8]}"
        ticket_version = self.state.state_version

        self.state.recorder.emit(
            EventType.SPEECH_PROPOSED,
            state_version=ticket_version,
            speech_id=speech_id,
            text_preview=text[:160],
        )

        guard_result = self.guard.check(text, speech_id=speech_id)
        if not guard_result.allowed:
            return False, None

        ticket = SpeechTicket(
            speech_id=speech_id,
            state_version=ticket_version,
            text=text,
            asserted_hypotheses=guard_result.asserted_hypotheses,
            depends_on=guard_result.depends_on,
        )
        if not self.fence.authorize_speech(ticket).allowed:
            return False, None

        record = SpeechRecord(
            speech_id=speech_id,
            state_version=ticket_version,
            text=text,
            asserted_hypotheses=list(guard_result.asserted_hypotheses),
            started_at=time.time(),
            completed_at=time.time(),
            heard_status="COMPLETED",
            heard_text=text,
        )
        self.state.register_speech(record)
        self.state.recorder.emit(
            EventType.AGENT_SPEECH_COMPLETED,
            state_version=self.state.state_version,
            speech_id=speech_id,
            text=text,
        )
        self.loop_detector.record_spoken_diagnosis(
            text, hypothesis_ids=list(guard_result.asserted_hypotheses)
        )
        return True, record

    def user_says(self, utterance: str) -> None:
        """Feed a caller turn through extraction and reconciliation."""
        self.state.turn += 1
        self.state.recorder.emit(
            EventType.USER_TRANSCRIPT_FINAL,
            state_version=self.state.state_version,
            transcript=utterance,
        )
        extractions = self.extractor.extract(utterance, self.state)
        if extractions:
            self.reconciler.apply(utterance, extractions)
        self.loop_detector.note_turn()

    def spoken_texts(self) -> list[str]:
        """Everything the caller actually heard, in order."""
        return [
            r.heard_text
            for r in sorted(self.state.speech_records.values(), key=lambda r: r.started_at or 0.0)
            if r.was_heard
        ]

    # -- scenarios -----------------------------------------------------------

    async def run_primary(self) -> RunOutcome:
        """T-PRIMARY: slow tool in flight, caller interrupts and corrects.

        Sequence:
          1. the agent proposes the naive card-block diagnosis and the caller hears it;
          2. a card-status check is issued (delayed) — this is the in-flight tool;
          3. while it is in flight the caller interrupts with the correction;
          4. the delayed result lands afterwards and must be fenced;
          5. the agent tries the same diagnosis again and must be blocked;
          6. the agent moves to delivery and escalates.
        """
        outcome = RunOutcome(scenario="primary_stale_fence", run_index=0, passed=False)
        state = self.state

        # 1. The naive diagnosis, heard by the caller.
        spoke_naive, _ = self.agent_says(NAIVE_DIAGNOSIS)
        outcome.checks["naive_diagnosis_was_spoken_first"] = spoke_naive

        # 2. Issue the slow card check. The delay comes from the fixture.
        delay_ms = self.backend.latency.get("get_card_status") or 3000
        self.backend.set_mock_tool_delay("get_card_status", delay_ms)
        version_at_issue = state.state_version
        task = asyncio.ensure_future(self.backend.get_card_status(self.fixture.customer_id))

        # 3. The caller interrupts partway through the tool call.
        await asyncio.sleep(min(delay_ms / 1000.0 * 0.4, 1.2))
        tool_still_in_flight = bool(state.pending_tools)
        outcome.checks["tool_was_still_in_flight_at_correction"] = tool_still_in_flight

        correction_started = time.perf_counter()
        self.user_says(CORRECTION_UTTERANCE)
        correction_applied = time.perf_counter()
        outcome.measured["correction_apply_ms"] = (correction_applied - correction_started) * 1000

        outcome.checks["state_version_incremented_once"] = (
            state.state_version == version_at_issue + 1
        )
        card_blocked = state.get_hypothesis("CARD_BLOCKED")
        outcome.checks["card_blocked_rejected"] = card_blocked.status is HypothesisStatus.REJECTED
        outcome.checks["rejection_cites_user_evidence"] = any(
            e.summary for e in card_blocked.contradicting_evidence
        )

        # 4. The delayed result lands after the correction.
        result, decision = await task
        fenced_at = time.perf_counter()
        outcome.measured["correction_to_fence_ms"] = (fenced_at - correction_applied) * 1000

        outcome.checks["late_result_is_stale"] = result.stale is True
        outcome.checks["late_result_cannot_speak"] = decision.may_speak is False
        outcome.checks["late_result_did_not_speak"] = result.triggered_speech is False
        outcome.checks["late_result_kept_as_evidence"] = result in state.completed_tools
        outcome.checks["stale_event_emitted"] = bool(
            state.recorder.of_type(EventType.TOOL_MARKED_STALE)
        )

        # 5. The agent tries the contradicted diagnosis again. It must not reach the caller.
        rejection_event = state.recorder.first(EventType.HYPOTHESIS_REJECTED)
        spoke_again, _ = self.agent_says(
            "I still think your card is blocked, that's why the OTP isn't coming."
        )
        outcome.checks["repeat_of_rejected_diagnosis_blocked"] = spoke_again is False

        # 6. Continue on the corrected branch.
        await self.backend.get_otp_generation_status(self.fixture.customer_id)
        delivery, delivery_decision = await self.backend.get_otp_delivery_status(
            self.fixture.customer_id
        )
        outcome.checks["unrelated_check_still_usable"] = delivery_decision.may_speak is True

        self._absorb_delivery(delivery)
        spoke_final, final_record = self.agent_says(
            "Your card is showing as active, so a card block doesn't explain this. "
            "The one-time password was generated, but delivery failed."
        )
        outcome.checks["corrected_response_was_spoken"] = spoke_final
        outcome.checks["final_response_mentions_delivery"] = bool(
            final_record and "deliver" in final_record.heard_text.lower()
        )

        # The central assertion: nothing the caller heard after the rejection asserts
        # the contradicted diagnosis.
        outcome.checks["no_rejected_assertion_after_rejection"] = self._no_rejected_assertion_after(
            rejection_event
        )

        packet = build_handoff_packet(state)
        outcome.checks["handoff_has_confirmed_rejected_and_attempted"] = bool(
            packet.rejected and packet.attempted and packet.user_corrections
        )
        outcome.checks["handoff_routes_to_delivery_team"] = (
            "delivery" in packet.recommended_destination.lower()
        )

        return self._finish(outcome)

    async def run_normal(self) -> RunOutcome:
        """T-A: no interruption, correct diagnosis reached on the evidence."""
        outcome = RunOutcome(scenario="normal_flow", run_index=0, passed=False)

        for check in (
            self.backend.get_card_status,
            self.backend.get_online_transaction_status,
            self.backend.get_registered_mobile_status,
            self.backend.get_otp_generation_status,
        ):
            await check(self.fixture.customer_id)
        delivery, _ = await self.backend.get_otp_delivery_status(self.fixture.customer_id)
        self._absorb_delivery(delivery)

        spoke, record = self.agent_says(
            "The one-time password was generated, but the message was never delivered. "
            "I'm checking the delivery service now."
        )
        outcome.checks["diagnosis_spoken"] = spoke
        outcome.checks["reached_delivery_diagnosis"] = bool(
            record and "deliver" in record.heard_text.lower()
        )
        outcome.checks["no_stale_results"] = all(not t.stale for t in self.state.completed_tools)
        outcome.checks["no_unearned_resolution_check"] = (
            self.guard.check("Is your issue resolved now?").allowed is False
        )
        outcome.checks["no_loop_detected"] = not self.loop_detector.assess().triggered
        return self._finish(outcome)

    async def run_loop(self) -> RunOutcome:
        """T-C: repetition without new evidence must change strategy or escalate."""
        outcome = RunOutcome(scenario="loop_detection", run_index=0, passed=False)

        self.agent_says("It looks like your card is blocked.")
        self.user_says("That didn't work, I still can't pay.")
        self.agent_says("I think the card might be blocked.")
        self.user_says("Still not receiving anything. Same problem.")

        assessment = self.loop_detector.assess()
        outcome.checks["loop_detected"] = assessment.triggered
        outcome.checks["loop_event_emitted"] = bool(
            self.state.recorder.of_type(EventType.LOOP_DETECTED)
        )
        outcome.checks["strategy_change_or_escalation_available"] = (
            assessment.suggested_branch is not None or self.loop_detector.next_branch() is None
        )
        return self._finish(outcome)

    async def run_tool_failure(self) -> RunOutcome:
        """T-D: a failed check is reported as unknown, never guessed."""
        outcome = RunOutcome(scenario="tool_failure", run_index=0, passed=False)

        result, _ = await self.backend.get_otp_delivery_status(self.fixture.customer_id)
        outcome.checks["tool_failed_as_configured"] = result.succeeded is False
        outcome.checks["no_payload_invented"] = result.payload == {}
        outcome.checks["delivery_hypothesis_not_promoted"] = (
            self.state.get_hypothesis("OTP_DELIVERY_FAILED").status is HypothesisStatus.ACTIVE
        )
        packet = build_handoff_packet(self.state)
        outcome.checks["failure_surfaced_as_open_question"] = any(
            "get_otp_delivery_status" in q for q in packet.open_questions
        )
        return self._finish(outcome)

    async def run_escalation(self) -> RunOutcome:
        """T-E: the handoff packet carries state, not a transcript."""
        outcome = RunOutcome(scenario="escalation", run_index=0, passed=False)

        for check in (
            self.backend.get_card_status,
            self.backend.get_online_transaction_status,
            self.backend.get_registered_mobile_status,
            self.backend.get_otp_generation_status,
        ):
            await check(self.fixture.customer_id)
        delivery, _ = await self.backend.get_otp_delivery_status(self.fixture.customer_id)
        self._absorb_delivery(delivery)

        self.state.confirm_fact("card_status", "ACTIVE")
        self.state.confirm_fact("otp_generation_status", "SUCCESS")
        self.user_says(CORRECTION_UTTERANCE)

        packet = build_handoff_packet(self.state)
        outcome.checks["has_confirmed_facts"] = bool(packet.confirmed)
        outcome.checks["has_rejected_hypotheses"] = bool(packet.rejected)
        outcome.checks["records_why_each_was_rejected"] = all(r["because"] for r in packet.rejected)
        outcome.checks["has_user_corrections"] = bool(packet.user_corrections)
        outcome.checks["has_attempted_actions"] = bool(packet.attempted)
        outcome.checks["has_recommended_destination"] = bool(packet.recommended_destination)
        outcome.checks["spoken_summary_is_short"] = len(packet.to_spoken_summary()) < 320
        outcome.state_snapshot = {"handoff_packet": packet.to_dict()}
        return self._finish(outcome)

    # -- helpers -------------------------------------------------------------

    def _absorb_delivery(self, result: ToolResult) -> None:
        if not result.succeeded:
            return
        from .resolution.hypotheses import Evidence, EvidenceSource

        status = str(result.payload.get("otp_delivery_status", "")).upper()
        if status != "FAILED":
            return
        self.state.support_hypothesis(
            "OTP_DELIVERY_FAILED",
            Evidence(
                id=f"ev_delivery_{uuid.uuid4().hex[:6]}",
                source=EvidenceSource.TOOL,
                summary="delivery failed at the message provider",
                observed_at_version=self.state.state_version,
                supports=True,
                detail=dict(result.payload),
            ),
        )
        self.state.confirm_fact("otp_delivery_status", status)

    def _no_rejected_assertion_after(self, rejection_event) -> bool:
        """Did any turn the caller HEARD after the rejection assert the rejected claim?

        Checked against the heard text, not the generated text — a sentence blocked
        before synthesis never reached the caller, and the claim being tested is about
        what the caller experienced.
        """
        if rejection_event is None:
            return True
        state = self.state
        rejected_ids = {h.id for h in state.rejected_hypotheses}
        for record in state.speech_records.values():
            if not record.was_heard:
                continue
            for hypothesis_id in rejected_ids:
                hypothesis = state.get_hypothesis(hypothesis_id)
                if hypothesis is None or hypothesis.rejected_at_version is None:
                    continue
                # State versions are the authoritative ordering boundary. Wall-clock
                # timestamps can tie on Windows during fast deterministic runs,
                # incorrectly making pre-correction speech look post-correction.
                if record.state_version < hypothesis.rejected_at_version:
                    continue
                if hypothesis.asserted_in(record.heard_text):
                    return False
        return True

    def _finish(self, outcome: RunOutcome) -> RunOutcome:
        outcome.failures = [name for name, ok in outcome.checks.items() if not ok]
        outcome.passed = not outcome.failures
        outcome.state_snapshot.update(self.state.snapshot())
        outcome.events = [e.to_dict() for e in self.state.recorder.events]
        return outcome


SCENARIOS: dict[str, tuple[str, str]] = {
    # name -> (fixture id, harness method)
    "primary_stale_fence": ("otp_slow_tool", "run_primary"),
    "normal_flow": ("otp_normal", "run_normal"),
    "loop_detection": ("otp_correction", "run_loop"),
    "tool_failure": ("otp_tool_failure", "run_tool_failure"),
    "escalation": ("otp_escalation", "run_escalation"),
}


async def run_scenario(name: str, *, run_index: int = 0, delay_ms: int | None = None) -> RunOutcome:
    """Run one named scenario once."""
    fixture_id, method_name = SCENARIOS[name]
    harness = ScenarioHarness(fixture_id, session_id=f"{name}_{run_index:03d}")
    if delay_ms is not None:
        harness.backend.set_mock_tool_delay("get_card_status", delay_ms)
    outcome: RunOutcome = await getattr(harness, method_name)()
    outcome.run_index = run_index
    return outcome
