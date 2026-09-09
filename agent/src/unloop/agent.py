"""UNLOOP — realtime voice support agent.

Wires the deterministic resolution engine (``resolution/``) into a LiveKit
``AgentSession`` with Rime as the speech provider.

The division of labour is deliberate and is the whole architecture:

* **LiveKit** owns realtime media — turn detection, barge-in, playback truncation.
* **Rime** owns speech — over its WebSocket streaming endpoint, with word timestamps.
* **UNLOOP** owns belief — what is established, what was refuted, what is obsolete.

LiveKit stopping the audio when the caller interrupts is necessary and not
sufficient. The audio stops; the *tool call* issued four seconds ago is still in
flight, and the response the LLM had already started generating is still queued. Those
are application state, and nothing in the media stack knows they are now wrong. That
gap is what ``tts_node`` and the stale fence close here.

Verified against livekit-agents 1.8.0 and livekit-plugins-rime 1.8.0; see
docs/IMPLEMENTATION_PLAN.md section 1 for how each API used here was checked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    ModelSettings,
    RunContext,
    TurnHandlingOptions,
    cli,
    function_tool,
    inference,
    room_io,
)
from livekit.agents.voice.events import (
    AgentFalseInterruptionEvent,
    AgentStateChangedEvent,
    ConversationItemAddedEvent,
    SpeechCreatedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)
from livekit.plugins import rime

from .config import AppConfig, load_dotenv_if_present, write_rime_config_artifact
from .domains import available_domains, get_domain
from .domains.base import DomainAdapter
from .fixtures.loader import LatencyTable, available_fixtures, load_fixture
from .language import (
    LanguageProfile,
    augment_hypotheses_for_language,
    available_languages,
    configure_session_language,
    get_language,
)
from .observability.events import EventType
from .prompts import branch_phrase, build_instructions, correction_acknowledgement
from .resolution.corrections import CorrectionExtractor, CorrectionReconciler
from .resolution.goals import GoalRouter
from .resolution.loop_detector import LoopDetector
from .resolution.output_guard import OutputGuard
from .resolution.stale_fence import SpeechTicket, StaleFence
from .resolution.state import EscalationStatus, ResolutionState, SpeechRecord
from .sandbox import DEMO_CUSTOMER_ID, SyntheticSupportSandbox
from .tools.escalation import build_handoff_packet, mark_escalated

logger = logging.getLogger("unloop")

load_dotenv_if_present()

#: Data channel topic the debug panel listens on.
STATE_TOPIC = "unloop.state"
#: Data channel topic the demo controls publish on.
CONTROL_TOPIC = "unloop.control"


class UnloopAgent(Agent):
    """The support agent. Tools gather evidence; the engine decides what it means."""

    def __init__(self, engine: ResolutionEngine) -> None:
        self.engine = engine
        super().__init__(
            instructions=build_instructions(
                engine.state,
                system_prompt=engine.adapter.instructions(),
                language=engine.language,
            )
        )
        # Decorated methods are discovered automatically by LiveKit. Keep the
        # proven explicit schemas, but expose only this adapter's operations to the
        # model so a hotel call cannot drift into restaurant or shopping behavior.
        allowed = {tool.exposed_name for tool in engine.adapter.all_tools} | {"escalate_to_human"}
        self._tools = [tool for tool in self._tools if tool.info.name in allowed]
        self._chat_ctx = self._chat_ctx.copy(tools=self._tools)

    # -- speech gate ---------------------------------------------------------

    async def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        """Gate every sentence on its way to Rime.

        This is the last point at which text can be stopped, and it is where the
        output guard runs. Gating happens *per sentence* rather than per response so
        the stream is not buffered: a response is checked as it is produced, and a
        clean first sentence starts synthesising while the second is still arriving.

        When a sentence is blocked, the rest of the response is dropped and replaced
        with a grounded correction built from actual state — not a canned apology.
        Letting the remainder through would mean speaking the tail of an argument
        whose premise we just refused.
        """
        guarded = self._guard_stream(text)
        async for frame in Agent.default.tts_node(self, guarded, model_settings):
            yield frame

    async def _guard_stream(self, text: AsyncIterable[str]) -> AsyncGenerator[str, None]:
        engine = self.engine
        buffer = ""
        blocked = False

        async for chunk in text:
            if blocked:
                continue
            buffer += chunk
            while True:
                sentence, remainder = _split_sentence(buffer)
                if sentence is None:
                    break
                buffer = remainder
                verdict = engine.gate_sentence(sentence)
                if verdict.allowed:
                    yield verdict.text
                else:
                    blocked = True
                    if verdict.replacement:
                        yield verdict.replacement
                    break
            if blocked:
                break

        if not blocked and buffer.strip():
            verdict = engine.gate_sentence(buffer)
            if verdict.allowed:
                yield verdict.text
            elif verdict.replacement:
                yield verdict.replacement

    # -- tools ---------------------------------------------------------------

    @function_tool
    async def lookup_customer(self, context: RunContext, identifier: str = "DEMO-1001") -> str:
        """Verify a synthetic customer using DEMO-1001 or a fake reservation/account ID."""
        return await self.engine.run_tool("lookup_customer", identifier=identifier)

    #
    # Docstrings are the model's tool descriptions, so they are written for the
    # model: what the tool establishes, and what it does not.

    @function_tool
    async def check_card_status(self, context: RunContext) -> str:
        """Check whether the customer's debit card is active, blocked or restricted.

        Establishes only the card's own status. It says nothing about whether online
        payments are enabled or whether a one-time password was delivered.
        """
        return await self.engine.run_tool("get_card_status")

    @function_tool
    async def check_online_transactions(self, context: RunContext) -> str:
        """Check whether online and e-commerce payments are switched on for the card."""
        return await self.engine.run_tool("get_online_transaction_status")

    @function_tool
    async def list_recent_transactions(self, context: RunContext, limit: int = 5) -> str:
        """List recent synthetic transactions for the authenticated demo customer.

        Use this when asked about the last, latest, or recent transaction or transaction history.
        """
        return await self.engine.run_tool("list_recent_transactions", limit=limit)

    @function_tool
    async def get_transaction(self, context: RunContext, transaction_id: str) -> str:
        """Look up a synthetic banking transaction by ID.

        Args:
            transaction_id: Full or spoken ID, for example TXN-501, 501, or five zero one.
        """
        return await self.engine.run_tool("get_transaction", transaction_id=transaction_id)

    @function_tool
    async def check_registered_mobile(self, context: RunContext) -> str:
        """Check whether the mobile number on file is verified.

        Returns the verification status only. Never returns the number itself.
        """
        return await self.engine.run_tool("get_registered_mobile_status")

    @function_tool
    async def check_otp_generation(self, context: RunContext) -> str:
        """Check whether the bank generated a one-time password for the payment.

        Generation succeeding does not mean the customer received it. If this returns
        SUCCESS, the next question is whether delivery worked.
        """
        return await self.engine.run_tool("get_otp_generation_status")

    @function_tool
    async def check_otp_delivery(self, context: RunContext) -> str:
        """Check whether the generated one-time password was delivered by SMS."""
        return await self.engine.run_tool("get_otp_delivery_status")

    @function_tool
    async def check_service_incidents(self, context: RunContext, service: str) -> str:
        """Check for known incidents on a downstream service.

        Args:
            service: The service to check, for example "sms_provider" or "card_network".
        """
        return await self.engine.run_tool("get_service_incidents", service=service)

    @function_tool
    async def resend_otp(self, context: RunContext) -> str:
        """Resend an OTP only after a delivery failure is confirmed; never request the code."""
        return await self.engine.run_tool("resend_otp")

    @function_tool
    async def check_refund_record(self, context: RunContext) -> str:
        """Check the merchant's record for an existing refund support case."""
        return await self.engine.run_tool("check_refund_record")

    @function_tool
    async def trace_refund_payment(self, context: RunContext) -> str:
        """Trace a processed refund through the payment rail."""
        return await self.engine.run_tool("trace_refund_payment")

    @function_tool
    async def reissue_refund(self, context: RunContext) -> str:
        """Reissue a refund only when investigation confirms it is stalled."""
        return await self.engine.run_tool("reissue_refund")

    @function_tool
    async def check_order_status(self, context: RunContext) -> str:
        """Verify the status of the customer's existing order."""
        return await self.engine.run_tool("check_order_status")

    @function_tool
    async def cancel_order(self, context: RunContext) -> str:
        """Cancel the customer's existing order when eligible."""
        return await self.engine.run_tool("cancel_order")

    @function_tool
    async def request_return(self, context: RunContext) -> str:
        """Open a return for the customer's existing delivered order."""
        return await self.engine.run_tool("request_return")

    @function_tool
    async def list_orders(self, context: RunContext) -> str:
        """List the authenticated synthetic customer's orders and their IDs."""
        return await self.engine.run_tool("list_orders")

    @function_tool
    async def get_order(self, context: RunContext, order_id: str) -> str:
        """Retrieve full synthetic order details by full, numeric, or spoken ID."""
        return await self.engine.run_tool("get_order", order_id=order_id)

    @function_tool
    async def list_refunds(self, context: RunContext) -> str:
        """List the authenticated synthetic customer's refunds and their IDs."""
        return await self.engine.run_tool("list_refunds")

    @function_tool
    async def get_refund(self, context: RunContext, refund_id: str) -> str:
        """Retrieve full synthetic refund details by full, numeric, or spoken ID."""
        return await self.engine.run_tool("get_refund", refund_id=refund_id)

    @function_tool
    async def check_platform_reservation(self, context: RunContext) -> str:
        """Check the existing restaurant reservation confirmation."""
        return await self.engine.run_tool("check_platform_reservation")

    @function_tool
    async def list_reservations(self, context: RunContext) -> str:
        """List the authenticated synthetic customer's restaurant reservations."""
        return await self.engine.run_tool("list_reservations")

    @function_tool
    async def get_reservation(self, context: RunContext, reservation_id: str) -> str:
        """Get an existing restaurant reservation by its synthetic identifier."""
        return await self.engine.run_tool("get_reservation", reservation_id=reservation_id)

    @function_tool
    async def create_reservation(
        self, context: RunContext, restaurant: str, date: str, time: str, party_size: int
    ) -> str:
        """Create a corrective reservation, not a restaurant discovery request."""
        return await self.engine.run_tool(
            "create_reservation", restaurant=restaurant, date=date, time=time, party_size=party_size
        )

    @function_tool
    async def check_restaurant_record(self, context: RunContext) -> str:
        """Check whether the restaurant received the confirmed reservation."""
        return await self.engine.run_tool("check_restaurant_record")

    @function_tool
    async def check_restaurant_availability(self, context: RunContext, requested_time: str) -> str:
        """Check availability at a requested time for the customer's existing reservation."""
        return await self.engine.run_tool(
            "check_restaurant_availability", requested_time=requested_time
        )

    @function_tool
    async def reschedule_restaurant_reservation(self, context: RunContext, new_time: str) -> str:
        """Move the existing reservation after confirming the desired time."""
        return await self.engine.run_tool("reschedule_restaurant_reservation", new_time=new_time)

    @function_tool
    async def change_restaurant_party_size(self, context: RunContext, party_size: int) -> str:
        """Change only the party size on the existing reservation."""
        return await self.engine.run_tool("change_restaurant_party_size", party_size=party_size)

    @function_tool
    async def cancel_restaurant_reservation(self, context: RunContext) -> str:
        """Cancel the customer's existing reservation."""
        return await self.engine.run_tool("cancel_restaurant_reservation")

    @function_tool
    async def rebook_reservation(self, context: RunContext) -> str:
        """Create a corrective replacement for the affected reservation."""
        return await self.engine.run_tool("rebook_reservation")

    @function_tool
    async def check_appointment_record(self, context: RunContext) -> str:
        """Check the current record for the affected salon appointment."""
        return await self.engine.run_tool("check_appointment_record")

    @function_tool
    async def check_appointment_history(self, context: RunContext) -> str:
        """Audit changes or cancellation of the affected appointment."""
        return await self.engine.run_tool("check_appointment_history")

    @function_tool
    async def reschedule_appointment(self, context: RunContext, new_time: str = "") -> str:
        """Correctively reschedule the affected appointment."""
        return await self.engine.run_tool("reschedule_appointment", new_time=new_time or None)

    @function_tool
    async def check_salon_availability(self, context: RunContext, requested_time: str) -> str:
        """Check salon availability for a requested corrective appointment time."""
        return await self.engine.run_tool("check_salon_availability", requested_time=requested_time)

    @function_tool
    async def change_appointment_service(self, context: RunContext, service: str) -> str:
        """Change the service on the customer's existing appointment."""
        return await self.engine.run_tool("change_appointment_service", service=service)

    @function_tool
    async def cancel_appointment(self, context: RunContext) -> str:
        """Cancel the customer's existing salon appointment."""
        return await self.engine.run_tool("cancel_appointment")

    @function_tool
    async def rebook_appointment(self, context: RunContext, new_time: str) -> str:
        """Rebook an affected appointment at a requested time."""
        return await self.engine.run_tool("rebook_appointment", new_time=new_time)

    @function_tool
    async def list_appointments(self, context: RunContext) -> str:
        """List the authenticated synthetic customer's appointments and their IDs."""
        return await self.engine.run_tool("list_appointments")

    @function_tool
    async def get_appointment(self, context: RunContext, appointment_id: str) -> str:
        """Retrieve full synthetic appointment details by full, numeric, or spoken ID."""
        return await self.engine.run_tool("get_appointment", appointment_id=appointment_id)

    @function_tool
    async def check_platform_booking(self, context: RunContext) -> str:
        """Check the existing hotel booking confirmation."""
        return await self.engine.run_tool("check_platform_booking")

    @function_tool
    async def check_hotel_record(self, context: RunContext) -> str:
        """Check whether the hotel property system contains the booking."""
        return await self.engine.run_tool("check_hotel_record")

    @function_tool
    async def reconcile_hotel_booking(self, context: RunContext) -> str:
        """Push a corrective reconciliation for the affected hotel booking."""
        return await self.engine.run_tool("reconcile_hotel_booking")

    @function_tool
    async def check_hotel_availability(
        self, context: RunContext, check_in: str, check_out: str
    ) -> str:
        """Check availability for alternate dates on the customer's existing stay."""
        return await self.engine.run_tool(
            "check_hotel_availability", check_in=check_in, check_out=check_out
        )

    @function_tool
    async def change_hotel_dates(self, context: RunContext, check_in: str, check_out: str) -> str:
        """Change dates on the customer's existing hotel booking."""
        return await self.engine.run_tool(
            "change_hotel_dates", check_in=check_in, check_out=check_out
        )

    @function_tool
    async def change_hotel_guest_count(self, context: RunContext, guest_count: int) -> str:
        """Change the guest count on the customer's existing hotel booking."""
        return await self.engine.run_tool("change_hotel_guest_count", guest_count=guest_count)

    @function_tool
    async def cancel_hotel_booking(self, context: RunContext) -> str:
        """Cancel the customer's existing hotel booking."""
        return await self.engine.run_tool("cancel_hotel_booking")

    @function_tool
    async def rebook_hotel_booking(self, context: RunContext, check_in: str, check_out: str) -> str:
        """Rebook an affected hotel stay for requested dates."""
        return await self.engine.run_tool(
            "rebook_hotel_booking", check_in=check_in, check_out=check_out
        )

    @function_tool
    async def list_bookings(self, context: RunContext) -> str:
        """List the authenticated synthetic customer's hotel bookings and their IDs."""
        return await self.engine.run_tool("list_bookings")

    @function_tool
    async def get_booking(self, context: RunContext, booking_id: str) -> str:
        """Retrieve full synthetic hotel booking details by full, numeric, or spoken ID."""
        return await self.engine.run_tool("get_booking", booking_id=booking_id)

    @function_tool
    async def escalate_to_human(self, context: RunContext, reason: str) -> str:
        """Hand the case to a human team with the full diagnostic context.

        Use when no automated check or fix remains. The customer will not have to
        repeat anything: everything confirmed and everything ruled out travels with
        the case.

        Args:
            reason: Short description of why this needs a human.
        """
        return await self.engine.escalate(reason)


class _GateVerdict:
    """Result of gating one sentence."""

    __slots__ = ("allowed", "reason", "replacement", "text")

    def __init__(
        self,
        allowed: bool,
        text: str,
        replacement: str = "",
        reason: str = "",
    ) -> None:
        self.allowed = allowed
        self.text = text
        self.replacement = replacement
        self.reason = reason


class ResolutionEngine:
    """Binds the deterministic resolution state to a live LiveKit session."""

    def __init__(
        self,
        config: AppConfig,
        fixture_id: str | None = None,
        *,
        domain_id: str | None = None,
        language_id: str | None = None,
        sandbox: SyntheticSupportSandbox | None = None,
    ) -> None:
        self.language: LanguageProfile = get_language(language_id)
        self.config = (
            configure_session_language(config, self.language) if language_id is not None else config
        )
        requested_adapter = get_domain(domain_id)
        selected_fixture = fixture_id or (
            requested_adapter.default_fixture if domain_id else config.default_fixture
        )
        self.fixture = load_fixture(selected_fixture)
        self.adapter: DomainAdapter = get_domain(domain_id or self.fixture.domain)
        if self.fixture.domain != self.adapter.domain_id:
            logger.warning(
                "fixture %s belongs to %s, using the %s domain default instead",
                self.fixture.fixture_id,
                self.fixture.domain,
                self.adapter.domain_id,
            )
            self.fixture = load_fixture(self.adapter.default_fixture)
        self.sandbox = sandbox or SyntheticSupportSandbox()
        self.state = ResolutionState(
            issue_type=f"{self.adapter.domain_id.upper()}_SUPPORT",
            issue_summary=f"{self.adapter.label} request — awaiting customer intent",
            hypotheses=[],
        )
        self.latency = LatencyTable(self.fixture.tool_delays_ms)
        self.backend = self.adapter.create_backend(
            self.fixture, self.state, self.latency, self.sandbox
        )
        self.fence = StaleFence(self.state)
        self.guard = OutputGuard(
            self.state,
            hypothesis_subjects=self.adapter.hypothesis_subjects,
            remediation_actions=self.adapter.remediation_actions,
        )
        self.loop_detector = LoopDetector(self.state)
        self.goal_router = GoalRouter(self.adapter.goals)
        self.extractor = CorrectionExtractor(
            denials=self.adapter.denial_rules,
            evidence_patterns=self.adapter.evidence_patterns,
            redirects=self.adapter.redirects,
            hypothesis_subjects=self.adapter.hypothesis_subjects,
        )
        self.reconciler = CorrectionReconciler(self.state, conflict_resolver=self.adapter.conflict)

        self.session: AgentSession | None = None
        self.agent: UnloopAgent | None = None
        self.room: rtc.Room | None = None

        #: speech_id -> ticket, for the speech-level fence.
        self._tickets: dict[str, SpeechTicket] = {}
        self._current_speech_id: str | None = None
        self._pending_regeneration: str | None = None
        #: Strong references to in-flight background tasks. asyncio holds only a weak
        #: reference to a running task, so a task that nothing else references can be
        #: garbage-collected mid-await. For publish_state that would drop a UI update;
        #: for on_user_transcript it would drop a caller correction, which is the one
        #: thing this system must never do.
        self._tasks: set[asyncio.Task[Any]] = set()

        self.state.recorder.emit(
            EventType.FIXTURE_LOADED,
            state_version=self.state.state_version,
            fixture_id=self.fixture.fixture_id,
            label=self.fixture.label,
            tool_delays_ms=self.fixture.tool_delays_ms,
        )

    def spawn(self, coro: Any) -> asyncio.Task[Any]:
        """Run a coroutine in the background, keeping a strong reference to it.

        LiveKit session events are synchronous callbacks, so async follow-up work has
        to be scheduled rather than awaited. See ``_tasks`` for why the reference
        matters.
        """
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # -- tools ---------------------------------------------------------------

    async def run_tool(self, tool_name: str, **kwargs: Any) -> str:
        """Run a backend check and return an ear-friendly summary for the model.

        The return value is deliberately *not* raw JSON. It is the sentence the model
        should reason from, and it says explicitly when a result is obsolete, so even
        a model that ignores the instruction cannot quote a superseded fact as
        current — the fence has already relabelled it.
        """
        definitions = {tool.name: tool for tool in self.adapter.all_tools}
        definition = definitions.get(tool_name)
        if definition is None:
            return f"That operation is not available for this {self.adapter.label.lower()} support case."
        current_goal = self.state.current_goal
        if (
            definition.goal_ids
            and current_goal is not None
            and current_goal.id not in definition.goal_ids
        ):
            return (
                "That operation belongs to the customer's previous request and is no longer available. "
                f"Continue with the current goal: {current_goal.label}."
            )
        if definition.corrective_action and definition.requires_hypothesis:
            hypothesis = self.state.get_hypothesis(definition.requires_hypothesis)
            if hypothesis is None or hypothesis.status.value != "SUPPORTED":
                return "That corrective action is premature. Complete the relevant support checks first."

        result, decision = await self.adapter.invoke(self.backend, tool_name, **kwargs)
        await self.publish_state()

        if not result.succeeded:
            return (
                f"That check did not complete ({result.status.value.lower()}). "
                "Tell the customer plainly that you could not verify it. Do not guess the answer."
            )

        if not decision.may_speak:
            # The result is real, but it answers a question the caller withdrew while
            # it was in flight. It stays in the record as historical evidence and is
            # explicitly marked unusable for speech.
            return (
                f"This result is out of date and must not be mentioned. "
                f"It was requested before the customer corrected you, and that correction "
                f"made it irrelevant ({decision.reason}). "
                f"Continue with the customer's current question instead."
            )

        self._absorb(result)
        await self.publish_state()
        return self.adapter.describe(result)

    def _absorb(self, result: Any) -> None:
        """Delegate domain interpretation while keeping state transitions shared."""
        self.adapter.absorb(self.state, result)

    # -- speech gating -------------------------------------------------------

    def gate_sentence(self, sentence: str) -> _GateVerdict:
        """Run the output guard over one sentence bound for Rime."""
        text = sentence.strip()
        if not text:
            return _GateVerdict(True, sentence)

        speech_id = self._current_speech_id or "unknown"
        result = self.guard.check(text, speech_id=speech_id)
        if result.allowed:
            # Rule 2 of the fence: a turn generated before a correction that
            # invalidated its subject is answering a withdrawn question.
            ticket = self._tickets.get(speech_id)
            if ticket is not None:
                probe = SpeechTicket(
                    speech_id=speech_id,
                    state_version=ticket.state_version,
                    text=text,
                    asserted_hypotheses=result.asserted_hypotheses,
                    depends_on=result.depends_on,
                    goal_id=ticket.goal_id,
                )
                decision = self.fence.authorize_speech(probe)
                if not decision.allowed:
                    return _GateVerdict(
                        False,
                        text,
                        replacement=self._recovery_sentence(result.asserted_hypotheses),
                        reason=decision.reason,
                    )
            return _GateVerdict(True, sentence)

        self._pending_regeneration = result.regeneration_hint
        return _GateVerdict(
            False,
            text,
            replacement=self._recovery_sentence(result.asserted_hypotheses),
            reason=result.reason,
        )

    def _recovery_sentence(self, asserted: tuple[str, ...]) -> str:
        """A grounded replacement for a blocked sentence.

        Built from real state — what was rejected, and which check is genuinely next —
        so the caller hears the conversation move on rather than stall.
        """
        rejected = [
            self.state.hypotheses[h].label
            for h in asserted
            if h in self.state.hypotheses and self.state.hypotheses[h].is_rejected
        ]
        label = rejected[0] if rejected else "that"
        next_step = branch_phrase(self.loop_detector.next_branch(), self.adapter.branch_phrases)
        return " " + correction_acknowledgement(label, next_step, language=self.language)

    # -- transcript ----------------------------------------------------------

    async def on_user_transcript(self, transcript: str) -> None:
        """Apply a final caller transcript to state.

        Runs *before* the model sees the turn, so a correction has already
        incremented the state version and rejected the hypothesis by the time any
        response is generated against it.
        """
        state = self.state
        state.turn += 1
        state.last_user_intent = transcript[:200]

        # User speech, never the fixture, decides whether diagnostic hypotheses
        # belong in the active state for this turn.
        detected_goal = self.goal_router.detect(transcript)
        if detected_goal is not None:
            if detected_goal.id in self.adapter.diagnostic_goal_ids:
                if not state.hypotheses:
                    for hypothesis in augment_hypotheses_for_language(
                        self.adapter.build_hypotheses(), self.language
                    ):
                        state.add_hypothesis(hypothesis)
            elif state.current_goal is None or state.current_goal.id != detected_goal.id:
                state.hypotheses.clear()
                state.loop_score = 0

        extractions = self.extractor.extract(transcript, state)
        if extractions:
            self.reconciler.apply(transcript, extractions)

        if detected_goal is not None:
            changed = state.set_current_goal(detected_goal, bump=not bool(extractions))
            if changed:
                state.loop_score = 0

        self.loop_detector.note_turn()
        assessment = self.loop_detector.assess()
        if assessment.triggered:
            branch = assessment.suggested_branch
            if branch is None:
                state.set_escalation(
                    EscalationStatus.RECOMMENDED,
                    reason="every diagnostic branch is exhausted",
                )
                state.set_strategy("escalate", reason="loop detected, no branches left")
            else:
                state.set_strategy(f"investigate_{branch}", reason="loop detected")

        if self.agent is not None:
            await self.agent.update_instructions(
                build_instructions(
                    state,
                    system_prompt=self.adapter.instructions(),
                    language=self.language,
                )
            )
        await self.publish_state()

    # -- escalation ----------------------------------------------------------

    async def escalate(self, reason: str) -> str:
        state = self.state
        packet = build_handoff_packet(
            state, destination_resolver=self.adapter.recommend_destination
        )

        case_result, _ = await self.backend.create_support_case(
            DEMO_CUSTOMER_ID,
            summary=state.issue_summary,
            evidence=packet.to_dict(),
        )
        case_id = str(case_result.payload.get("case_id", "")) or "unknown"
        packet.case_id = case_id

        await self.backend.escalate_to_human(case_id, packet.to_dict())
        mark_escalated(state, reason)
        await self.publish_state()

        return (
            f"Case created and routed to {packet.recommended_destination}. "
            f"Say this to the customer, briefly and in your own words: {packet.to_spoken_summary()}"
        )

    # -- debug channel -------------------------------------------------------

    async def publish_state(self) -> None:
        """Push the current state snapshot to the debug panel."""
        if self.room is None:
            return
        payload = {
            "type": "state",
            "state": self.state.snapshot(),
            "speech": self.speech_provider_info(),
            "fixture": {
                "domain": self.adapter.domain_id,
                "fixture_id": self.fixture.fixture_id,
                "label": self.fixture.label,
                "primary_delay_tool": self.adapter.primary_delay_tool,
                "tool_delays_ms": self.latency.snapshot(),
                "available": available_fixtures(self.adapter.domain_id),
                "domains": available_domains(),
                "languages": available_languages(),
                "language": self.language.id,
            },
            "loop": {"score": self.state.loop_score, "strategy": self.state.current_strategy},
            "handoff": build_handoff_packet(
                self.state, destination_resolver=self.adapter.recommend_destination
            ).to_dict(),
            "sandbox": self.sandbox.snapshot(DEMO_CUSTOMER_ID, self.adapter.domain_id),
        }
        try:
            await self.room.local_participant.publish_data(
                json.dumps(payload, default=str).encode("utf-8"),
                topic=STATE_TOPIC,
                reliable=True,
            )
        except Exception as exc:
            logger.debug("could not publish debug state: %s", exc)

    def speech_provider_info(self) -> dict[str, Any]:
        """What the SPEECH badge in the UI reads from.

        Reports the live configuration rather than a hard-coded string, so if the
        provider were ever swapped the badge would say so.
        """
        rime_config = self.config.rime
        return {
            "provider": "Rime",
            "model": rime_config.model,
            "speaker": rime_config.speaker,
            "language": rime_config.language,
            "mode": self.language.id,
            "label": self.language.label,
            "stt_language": self.config.stt.language,
            "transport": rime_config.transport,
            "base_url": rime_config.base_url,
            "resolved_endpoint": rime_config.resolved_endpoint(),
            "region": rime_config.region,
            "sample_rate": rime_config.sample_rate,
            "segment": rime_config.segment,
            "audio_format": rime_config.audio_format,
        }

    # -- demo controls -------------------------------------------------------

    def handle_control(self, message: dict[str, Any]) -> None:
        """Handle a demo-panel control message.

        Controls set fixture conditions only (ADR-009). There is no control that can
        write a transcript, force a hypothesis, or change what a tool returns.
        """
        action = message.get("action")
        if action == "set_tool_delay":
            tool = str(message.get("tool", self.adapter.primary_delay_tool))
            delay = int(message.get("delay_ms", 0))
            self.backend.set_mock_tool_delay(tool, delay)
        elif action == "clear_delays":
            self.latency.clear()
        elif action == "reset_demo_data":
            self.sandbox.reset_demo_data()
            self.spawn(self.publish_state())


# ---------------------------------------------------------------------------
# Session wiring
# ---------------------------------------------------------------------------


def build_session(config: AppConfig, engine: ResolutionEngine) -> AgentSession:
    """Construct the AgentSession with the judged speech path.

    Rime is constructed directly here with our own key (ADR-001), so the provider,
    endpoint, model, voice, transport and sample rate in the evidence artifact are
    the same values this session actually uses.
    """
    tts = rime.TTS(**config.rime.plugin_kwargs())

    return AgentSession(
        stt=inference.STT(
            model=config.stt.model,
            language=config.stt.language,
            extra_kwargs={"keyterm": list(config.stt.keyterms)},
        ),
        llm=inference.LLM(model=config.llm.model),
        tts=tts,
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={
                # Adaptive interruption distinguishes a real interruption from a
                # backchannel like "mhm", which matters here: the caller saying "uh
                # huh" while we explain must not tear down the turn, but "no, my card
                # isn't blocked" must, immediately.
                "mode": "adaptive",
                "min_duration": 0.4,
                "false_interruption_timeout": 2.0,
                "resume_false_interruption": True,
            },
            # Kept ON deliberately (ADR-007). Preemptive generation is what
            # manufactures obsolete responses, and the fence is built to handle them.
            # Disabling it would remove the hard part of the problem rather than solve it.
            preemptive_generation={"enabled": True},
        ),
        # Rime's WebSocket path returns word timestamps, so the "what did the caller
        # actually hear" boundary is measured from real word timings rather than an
        # estimated speaking rate. See ADR-006.
        use_tts_aligned_transcript=True,
    )


def attach_instrumentation(session: AgentSession, engine: ResolutionEngine) -> None:
    """Bridge LiveKit session events into the UNLOOP event log."""
    state = engine.state
    recorder = state.recorder

    @session.on("user_state_changed")
    def _on_user_state(ev: UserStateChangedEvent) -> None:
        if ev.new_state == "speaking":
            recorder.emit(EventType.USER_SPEECH_START, state_version=state.state_version)
            # An interruption is caller speech beginning while the agent has the floor.
            if session.agent_state == "speaking":
                recorder.emit(
                    EventType.INTERRUPTION_DETECTED,
                    state_version=state.state_version,
                    speech_id=engine._current_speech_id,
                )
                recorder.emit(
                    EventType.AGENT_AUDIO_STOP_REQUESTED,
                    state_version=state.state_version,
                    speech_id=engine._current_speech_id,
                )

    @session.on("agent_state_changed")
    def _on_agent_state(ev: AgentStateChangedEvent) -> None:
        if ev.new_state == "speaking":
            recorder.emit(
                EventType.AGENT_SPEECH_STARTED,
                state_version=state.state_version,
                speech_id=engine._current_speech_id,
            )
            record = engine._tickets.get(engine._current_speech_id or "")
            if record is not None:
                speech = state.speech_records.get(record.speech_id)
                if speech is not None:
                    speech.started_at = time.time()
                    speech.heard_status = "PARTIAL"
        elif ev.old_state == "speaking":
            recorder.emit(
                EventType.AGENT_AUDIO_STOPPED,
                state_version=state.state_version,
                speech_id=engine._current_speech_id,
            )

    @session.on("speech_created")
    def _on_speech_created(ev: SpeechCreatedEvent) -> None:
        """Stamp every generated turn with the state version it was born under.

        This is the moment that makes the speech fence possible. Without it, a
        response generated before a correction is indistinguishable from one
        generated after.
        """
        speech_id = ev.speech_handle.id
        engine._current_speech_id = speech_id
        ticket = SpeechTicket(
            speech_id=speech_id,
            state_version=state.state_version,
            text="",
            intent=ev.source,
            goal_id=state.current_goal.id if state.current_goal else None,
        )
        engine._tickets[speech_id] = ticket
        state.register_speech(
            SpeechRecord(
                speech_id=speech_id,
                state_version=state.state_version,
                text="",
                intent=ev.source,
            )
        )
        recorder.emit(
            EventType.SPEECH_PROPOSED,
            state_version=state.state_version,
            speech_id=speech_id,
            source=ev.source,
            user_initiated=ev.user_initiated,
        )

        def _on_done(handle) -> None:
            record = state.speech_records.get(speech_id)
            if record is None:
                return
            if handle.interrupted:
                record.heard_status = "INTERRUPTED"
                record.interrupted_at = time.time()
                recorder.emit(
                    EventType.AGENT_INTERRUPTED,
                    state_version=state.state_version,
                    speech_id=speech_id,
                )
            else:
                record.completed_at = time.time()
                record.heard_status = "COMPLETED"
                recorder.emit(
                    EventType.AGENT_SPEECH_COMPLETED,
                    state_version=state.state_version,
                    speech_id=speech_id,
                )

        ev.speech_handle.add_done_callback(_on_done)

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        """Record what was actually audible.

        For an interrupted assistant turn, livekit-agents 1.8.0 replaces the message
        content with the synchronized transcript of what was played (and empties it
        entirely if no frame of the agent's own audio was heard). That truncated text
        — not the generated text — is what we treat as communicated.
        """
        item = ev.item
        if getattr(item, "role", None) != "assistant":
            return
        text = item.text_content or ""
        interrupted = bool(getattr(item, "interrupted", False))

        record = state.speech_records.get(engine._current_speech_id or "")
        if record is not None:
            record.heard_text = text
            record.aligned = True  # Rime WS word timestamps back the synchronizer
            if interrupted:
                record.heard_status = "INTERRUPTED" if text.strip() else "NOT_STARTED"
            else:
                record.heard_status = "COMPLETED"

            asserted, _ = engine.guard.analyse(text)
            record.asserted_hypotheses = list(asserted)
            if record.was_heard:
                engine.loop_detector.record_spoken_diagnosis(text, hypothesis_ids=list(asserted))
                state.last_agent_intent = text[:200]

        engine.spawn(engine.publish_state())

    @session.on("user_input_transcribed")
    def _on_transcript(ev: UserInputTranscribedEvent) -> None:
        if not ev.is_final:
            recorder.emit(
                EventType.USER_TRANSCRIPT_INTERIM,
                state_version=state.state_version,
                transcript=ev.transcript,
            )
            return
        recorder.emit(
            EventType.USER_TRANSCRIPT_FINAL,
            state_version=state.state_version,
            transcript=ev.transcript,
        )
        engine.spawn(engine.on_user_transcript(ev.transcript))

    @session.on("agent_false_interruption")
    def _on_false_interruption(ev: AgentFalseInterruptionEvent) -> None:
        """A backchannel, not a real interruption (T-F).

        Crucially this must NOT bump the state version: "mhm" is not a correction,
        and treating it as one would fence perfectly good work.
        """
        recorder.emit(
            EventType.FALSE_INTERRUPTION,
            state_version=state.state_version,
            resumed=ev.resumed,
        )

    @session.on("error")
    def _on_error(ev) -> None:
        recorder.emit(
            EventType.ERROR,
            state_version=state.state_version,
            source=type(getattr(ev, "error", ev)).__name__,
        )


def _split_sentence(buffer: str) -> tuple[str | None, str]:
    """Split off the first complete sentence, if there is one.

    Sentence-level rather than response-level gating keeps the stream flowing: a
    clean first sentence starts synthesising while the rest is still being generated.
    """
    for index, char in enumerate(buffer):
        # Hindi commonly uses the danda as its sentence terminator. Treating it as
        # a boundary preserves the same sentence-level guard and streaming latency.
        if char in ".!?।":
            following = buffer[index + 1 : index + 2]
            if following in ("", " ", "\n", '"', "'"):
                return buffer[: index + 1], buffer[index + 1 :]
    return None, buffer


server = AgentServer()


@server.rtc_session(agent_name="unloop")
async def unloop_session(ctx: JobContext) -> None:
    config = AppConfig.from_env()
    logging.getLogger().setLevel(config.log_level)

    problems = config.rime.validate()
    if problems:
        for problem in problems:
            logger.error("Rime configuration problem: %s", problem)
        raise RuntimeError(f"refusing to start with an invalid Rime configuration: {problems}")

    ctx.log_context_fields = {"room": ctx.room.name}

    domain_id: str | None = None
    language_id: str | None = None
    fixture_id: str | None = None
    try:
        dispatch_metadata = json.loads(ctx.job.metadata or "{}")
        domain_id = str(dispatch_metadata.get("domain") or "") or None
        language_id = str(dispatch_metadata.get("language") or "") or None
        fixture_id = str(dispatch_metadata.get("fixture") or "") or None
    except (TypeError, ValueError):
        logger.warning("ignoring invalid agent dispatch metadata")

    sandbox = SyntheticSupportSandbox(config.artifacts_dir / "synthetic_support.sqlite3")
    engine = ResolutionEngine(
        config,
        fixture_id=fixture_id,
        domain_id=domain_id,
        language_id=language_id,
        sandbox=sandbox,
    )
    config = engine.config
    session_problems = config.rime.validate()
    if session_problems:
        for problem in session_problems:
            logger.error("Rime session language configuration problem: %s", problem)
        raise RuntimeError(
            f"refusing to start with an invalid Rime session configuration: {session_problems}"
        )

    engine.room = ctx.room

    try:
        write_rime_config_artifact(config)
    except OSError as exc:
        logger.warning("could not write the Rime config artifact: %s", exc)

    session = build_session(config, engine)
    agent = UnloopAgent(engine)
    engine.session = session
    engine.agent = agent

    attach_instrumentation(session, engine)

    @ctx.room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        if packet.topic != CONTROL_TOPIC or not config.demo_mode:
            return
        try:
            engine.handle_control(json.loads(packet.data.decode("utf-8")))
        except (ValueError, KeyError) as exc:
            logger.debug("ignoring malformed control message: %s", exc)

    engine.state.recorder.emit(
        EventType.CALL_STARTED,
        state_version=engine.state.state_version,
        room=ctx.room.name,
        fixture=engine.fixture.fixture_id,
        speech_provider=engine.speech_provider_info(),
    )

    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(),
    )
    await ctx.connect()
    await engine.publish_state()
    await session.say(engine.language.opening_line or engine.adapter.opening_line)


if __name__ == "__main__":
    cli.run_app(server)
