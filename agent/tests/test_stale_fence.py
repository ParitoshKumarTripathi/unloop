"""T-PRIMARY and friends: the stale-result fence.

These are the tests the whole project is judged on. They are deterministic — no
model, no network, no key — so a pass means the invariant holds, not that a model
happened to behave this time.
"""

from __future__ import annotations

import asyncio

import pytest

from unloop.fixtures.loader import load_fixture
from unloop.observability.events import EventType
from unloop.resolution.corrections import CorrectionExtractor, CorrectionReconciler
from unloop.resolution.hypotheses import HypothesisStatus, build_otp_hypotheses
from unloop.resolution.stale_fence import FenceVerdict, SpeechTicket, StaleFence
from unloop.resolution.state import ResolutionState
from unloop.tools.banking import SupportBackend
from unloop.tools.types import Subject


def make_state(fixture_id: str = "otp_slow_tool") -> tuple[ResolutionState, SupportBackend]:
    fixture = load_fixture(fixture_id)
    state = ResolutionState(
        issue_type="OTP_NOT_RECEIVED",
        issue_summary="Debit card payment OTP is not being received",
        hypotheses=build_otp_hypotheses(),
    )
    return state, SupportBackend(fixture, state)


CORRECTION_UTTERANCE = (
    "No, my card is not blocked. I used it five minutes ago. Check the OTP delivery."
)


def apply_correction(state: ResolutionState, utterance: str = CORRECTION_UTTERANCE) -> None:
    extractions = CorrectionExtractor().extract(utterance, state)
    CorrectionReconciler(state).apply(utterance, extractions)


# ---------------------------------------------------------------------------
# T-PRIMARY
# ---------------------------------------------------------------------------


async def test_primary_slow_tool_result_arriving_after_correction_is_fenced():
    """The headline claim, end to end.

    A card-status check is issued, the caller interrupts and refutes the card
    hypothesis while it is in flight, and the result arrives afterwards. It must be
    marked stale, must not be able to speak, and must not resurrect CARD_BLOCKED.
    """
    state, backend = make_state("otp_slow_tool")
    backend.set_mock_tool_delay("get_card_status", 300)  # shortened; behaviour identical

    version_at_issue = state.state_version
    task = asyncio.create_task(backend.get_card_status("demo_customer_001"))

    # The caller interrupts while the tool is still in flight.
    await asyncio.sleep(0.05)
    assert state.pending_tools, "the tool should still be in flight when the caller corrects us"
    apply_correction(state)

    result, decision = await task

    # 2. the version moved exactly once
    assert state.state_version == version_at_issue + 1

    # 3. CARD_BLOCKED is rejected, with the caller's evidence recorded
    card_blocked = state.get_hypothesis("CARD_BLOCKED")
    assert card_blocked.status is HypothesisStatus.REJECTED
    assert card_blocked.rejected_at_version == state.state_version
    assert any(
        "recent successful card use" in e.summary for e in card_blocked.contradicting_evidence
    )

    # 4. the late result is superseded, stale, and cannot speak
    assert result.state_version == version_at_issue
    assert result.state_version < state.state_version
    assert decision.verdict is FenceVerdict.SUPERSEDED
    assert result.stale is True
    assert decision.may_speak is False
    assert result.triggered_speech is False

    # the fence left a trail
    stale_events = state.recorder.of_type(EventType.TOOL_MARKED_STALE)
    assert len(stale_events) == 1
    assert stale_events[0].meta["tool_name"] == "get_card_status"
    assert stale_events[0].meta["originating_state_version"] == version_at_issue


async def test_stale_result_cannot_resurrect_the_rejected_hypothesis():
    """The subtlest failure mode: evidence older than the rejection reviving it."""
    from unloop.resolution.hypotheses import Evidence, EvidenceSource

    state, backend = make_state("otp_slow_tool")
    backend.set_mock_tool_delay("get_card_status", 200)

    version_at_issue = state.state_version
    task = asyncio.create_task(backend.get_card_status("demo_customer_001"))
    await asyncio.sleep(0.02)
    apply_correction(state)
    result, _ = await task

    card_blocked = state.get_hypothesis("CARD_BLOCKED")

    # Evidence stamped with the version the tool was ISSUED under - i.e. from before
    # the correction. It must not be able to undo the rejection.
    stale_support = Evidence(
        id="ev_stale_tool",
        source=EvidenceSource.TOOL,
        summary="card status check (issued before the correction)",
        observed_at_version=result.state_version,
        supports=True,
    )
    assert card_blocked.can_reactivate(stale_support) is False
    assert state.reactivate_hypothesis("CARD_BLOCKED", stale_support) is None
    assert card_blocked.status is HypothesisStatus.REJECTED

    # Genuinely new evidence, observed after the rejection, may reopen it. Refusing
    # forever would be its own failure mode.
    fresh_support = Evidence(
        id="ev_fresh_tool",
        source=EvidenceSource.TOOL,
        summary="card was blocked by fraud rules just now",
        observed_at_version=state.state_version + 1,
        supports=True,
    )
    assert card_blocked.can_reactivate(fresh_support) is True


async def test_unrelated_subject_survives_a_correction():
    """A late result about a different subject is not collateral damage.

    Discarding every late result would pass the headline test and be wrong: the OTP
    delivery check does not stop being true because the caller corrected us about the
    card.
    """
    state, backend = make_state("otp_slow_tool")
    backend.set_mock_tool_delay("get_otp_delivery_status", 250)

    task = asyncio.create_task(backend.get_otp_delivery_status("demo_customer_001"))
    await asyncio.sleep(0.02)
    apply_correction(state)
    result, decision = await task

    assert result.state_version < state.state_version
    assert decision.verdict is FenceVerdict.RECONCILABLE
    assert result.stale is False
    assert decision.may_speak is True


async def test_fresh_result_is_fresh():
    state, backend = make_state("otp_normal")
    result, decision = await backend.get_card_status("demo_customer_001")
    assert decision.verdict is FenceVerdict.FRESH
    assert result.stale is False
    assert decision.may_speak is True


# ---------------------------------------------------------------------------
# Speech fencing
# ---------------------------------------------------------------------------


def test_speech_generated_before_a_correction_is_blocked():
    """ADR-007: preemptive generation manufactures exactly this ticket."""
    state, _ = make_state()
    ticket = SpeechTicket(
        speech_id="sp_1",
        state_version=state.state_version,
        text="It looks like your card might be blocked, which would stop the OTP.",
        asserted_hypotheses=("CARD_BLOCKED",),
        depends_on=frozenset({Subject.CARD}),
    )
    fence = StaleFence(state)
    assert fence.authorize_speech(ticket).allowed is True

    apply_correction(state)

    decision = fence.authorize_speech(ticket)
    assert decision.allowed is False
    # Rule 1 fires first: it asserts a now-rejected hypothesis.
    assert decision.blocking_rule == "REJECTED_HYPOTHESIS"
    assert "CARD_BLOCKED" in decision.blocked_hypotheses
    assert state.recorder.of_type(EventType.OUTPUT_GUARD_REJECTION)


def test_speech_about_an_invalidated_subject_is_blocked_even_without_a_named_hypothesis():
    """Rule 2 catches obsolete turns whose wording names no hypothesis at all."""
    state, _ = make_state()
    ticket = SpeechTicket(
        speech_id="sp_2",
        state_version=state.state_version,
        text="Let me just finish checking that for you.",
        depends_on=frozenset({Subject.CARD}),
    )
    apply_correction(state)

    decision = StaleFence(state).authorize_speech(ticket)
    assert decision.allowed is False
    assert decision.blocking_rule == "SUPERSEDED_SPEECH"
    assert state.recorder.of_type(EventType.SPEECH_FENCED_STALE)


def test_speech_that_only_drifted_in_version_is_still_allowed():
    """Being old is not the same as being wrong."""
    state, _ = make_state()
    ticket = SpeechTicket(
        speech_id="sp_3",
        state_version=state.state_version,
        text="The one-time password was generated on our side.",
        depends_on=frozenset({Subject.OTP_GENERATION}),
    )
    apply_correction(state)
    assert StaleFence(state).authorize_speech(ticket).allowed is True


@pytest.mark.parametrize("runs", [20])
async def test_no_stale_leakage_across_repeated_runs(runs: int):
    """The acceptance target: zero stale leakage in 20 runs."""
    leaks = 0
    recurrences = 0
    for _ in range(runs):
        state, backend = make_state("otp_slow_tool")
        backend.set_mock_tool_delay("get_card_status", 120)
        task = asyncio.create_task(backend.get_card_status("demo_customer_001"))
        await asyncio.sleep(0.01)
        apply_correction(state)
        result, decision = await task

        if result.triggered_speech or decision.may_speak:
            leaks += 1
        if state.get_hypothesis("CARD_BLOCKED").status is not HypothesisStatus.REJECTED:
            recurrences += 1

    assert leaks == 0, f"stale result was speakable in {leaks}/{runs} runs"
    assert recurrences == 0, f"contradicted diagnosis survived in {recurrences}/{runs} runs"
