"""T-B, T-C, T-E: correction extraction, loop detection, escalation packet."""

from __future__ import annotations

import pytest

from unloop.fixtures.loader import load_fixture
from unloop.observability.events import EventType
from unloop.resolution.corrections import (
    CorrectionExtractor,
    CorrectionReconciler,
    ExtractionType,
)
from unloop.resolution.hypotheses import HypothesisStatus, build_otp_hypotheses
from unloop.resolution.loop_detector import LoopDetector, LoopSignal, normalise_diagnosis
from unloop.resolution.state import ResolutionState, SpeechRecord
from unloop.tools.banking import SupportBackend
from unloop.tools.escalation import build_handoff_packet, recommend_destination
from unloop.tools.types import Subject


def make_state(fixture_id: str = "otp_correction") -> tuple[ResolutionState, SupportBackend]:
    fixture = load_fixture(fixture_id)
    state = ResolutionState(
        issue_type="OTP_NOT_RECEIVED",
        issue_summary="Debit card payment OTP is not being received",
        hypotheses=build_otp_hypotheses(),
    )
    return state, SupportBackend(fixture, state)


def heard(state: ResolutionState, speech_id: str, text: str, hypotheses: list[str]) -> SpeechRecord:
    """Register a turn the caller actually heard."""
    record = SpeechRecord(
        speech_id=speech_id,
        state_version=state.state_version,
        text=text,
        asserted_hypotheses=hypotheses,
        started_at=1.0,
        completed_at=2.0,
        heard_status="COMPLETED",
        heard_text=text,
    )
    return state.register_speech(record)


# ---------------------------------------------------------------------------
# Correction extraction
# ---------------------------------------------------------------------------


def test_the_headline_utterance_is_fully_decomposed():
    """One sentence, three separate structured facts."""
    state, _ = make_state()
    utterance = "No, my card is not blocked. I used it five minutes ago. Check the OTP delivery."
    extractions = CorrectionExtractor().extract(utterance, state)

    kinds = [e.type for e in extractions]
    assert ExtractionType.CORRECTION in kinds
    assert ExtractionType.REDIRECT in kinds

    correction = next(e for e in extractions if e.type is ExtractionType.CORRECTION)
    assert correction.target == "CARD_BLOCKED"
    assert correction.evidence == "caller reports recent successful card use"
    assert correction.invalidates == frozenset({Subject.CARD})

    redirect = next(e for e in extractions if e.type is ExtractionType.REDIRECT)
    assert redirect.redirect_to is Subject.OTP_DELIVERY


@pytest.mark.parametrize(
    "utterance",
    [
        "My card is not blocked.",
        "The card isn't blocked, I just used it.",
        "No, there's no card block, it works fine.",
        "My card is fine, I used it this morning.",
    ],
)
def test_card_denials_are_recognised(utterance: str):
    state, _ = make_state()
    extractions = CorrectionExtractor().extract(utterance, state)
    assert any(e.target == "CARD_BLOCKED" for e in extractions), utterance


def test_a_bare_no_denies_the_last_thing_the_caller_actually_heard():
    state, _ = make_state()
    heard(state, "sp_1", "It looks like your card is blocked.", ["CARD_BLOCKED"])

    extractions = CorrectionExtractor().extract("No, that's not it.", state)
    assert [e.target for e in extractions] == ["CARD_BLOCKED"]


def test_a_bare_no_cannot_deny_a_turn_that_was_never_heard():
    """A diagnosis the caller never heard is not one they can be denying."""
    state, _ = make_state()
    state.register_speech(
        SpeechRecord(
            speech_id="sp_unheard",
            state_version=state.state_version,
            text="It looks like your card is blocked.",
            asserted_hypotheses=["CARD_BLOCKED"],
            heard_status="NOT_STARTED",
        )
    )
    assert CorrectionExtractor().extract("No, that's not it.", state) == []


def test_reconciler_rejects_the_hypothesis_and_bumps_the_version():
    state, _ = make_state()
    before = state.state_version

    utterance = "No, my card is not blocked. I used it five minutes ago."
    extractor = CorrectionExtractor()
    corrections = CorrectionReconciler(state).apply(utterance, extractor.extract(utterance, state))

    assert len(corrections) == 1
    assert state.state_version == before + 1
    assert state.get_hypothesis("CARD_BLOCKED").status is HypothesisStatus.REJECTED
    assert state.subjects_invalidated_since(before) == {Subject.CARD}

    correction_events = state.recorder.of_type(EventType.USER_CORRECTION)
    assert len(correction_events) == 1
    assert correction_events[0].meta["target_hypothesis"] == "CARD_BLOCKED"


async def test_caller_and_backend_disagreement_is_recorded_not_silently_resolved():
    """If the backend says BLOCKED and the caller says otherwise, both are kept.

    The hypothesis is still rejected — the caller is holding the card — but the
    conflict is flagged so the human who picks this up can see it. Quietly deciding
    the customer is wrong is the behaviour this product exists to eliminate.
    """
    state, backend = make_state()
    backend.sandbox.update_record(
        "DEMO-1001", "banking", "card", {"status": "BLOCKED"}, action="TEST_SETUP"
    )
    await backend.get_card_status("demo_customer_001")

    utterance = "My card is not blocked, I used it five minutes ago."
    CorrectionReconciler(state).apply(utterance, CorrectionExtractor().extract(utterance, state))

    assert state.get_hypothesis("CARD_BLOCKED").status is HypothesisStatus.REJECTED
    conflicts = [e for e in state.recorder.events if e.meta.get("signal") == "caller_tool_conflict"]
    assert len(conflicts) == 1
    assert "BLOCKED" in conflicts[0].meta["detail"]

    packet = build_handoff_packet(state)
    assert packet.conflicts and "BLOCKED" in packet.conflicts[0]


# ---------------------------------------------------------------------------
# Loop detection
# ---------------------------------------------------------------------------


def test_paraphrase_does_not_defeat_repetition_detection():
    a = normalise_diagnosis("So it looks like your card might be blocked.")
    b = normalise_diagnosis("I think the card is blocked, sir.")
    assert a == b


def test_repeating_a_diagnosis_without_new_evidence_is_a_loop():
    state, _ = make_state()
    detector = LoopDetector(state)

    detector.record_spoken_diagnosis("It looks like your card is blocked.")
    assert detector.assess().triggered is False

    detector.record_spoken_diagnosis("I think your card is blocked.")
    assessment = detector.assess()

    assert LoopSignal.DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE in assessment.signals
    assert assessment.triggered is True
    assert state.recorder.of_type(EventType.LOOP_DETECTED)


async def test_new_evidence_between_repeats_is_not_a_loop():
    """Saying the same thing again after learning something new is legitimate."""
    state, backend = make_state()
    detector = LoopDetector(state)

    detector.record_spoken_diagnosis("The OTP delivery may have failed.")
    await backend.get_otp_delivery_status("demo_customer_001")
    detector.record_spoken_diagnosis("The OTP delivery may have failed.")

    assessment = detector.assess()
    assert LoopSignal.DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE not in assessment.signals


def test_two_ineffective_reports_trigger_a_loop():
    state, _ = make_state()
    detector = LoopDetector(state)
    reconciler = CorrectionReconciler(state)
    extractor = CorrectionExtractor()

    for utterance in ("That didn't work.", "Still not receiving anything."):
        reconciler.apply(utterance, extractor.extract(utterance, state))

    assessment = detector.assess()
    assert LoopSignal.REPEATED_INEFFECTIVE_REPORTS in assessment.signals
    assert assessment.triggered is True


def test_a_blocked_reproposal_is_itself_a_loop_signal():
    """The guard stopping a repeat is evidence the generator is stuck."""
    from unloop.resolution.output_guard import OutputGuard

    state, _ = make_state()
    utterance = "My card is not blocked."
    CorrectionReconciler(state).apply(utterance, CorrectionExtractor().extract(utterance, state))

    OutputGuard(state).check("It looks like your card is blocked.", speech_id="sp_retry")

    assessment = LoopDetector(state).assess()
    assert LoopSignal.REJECTED_HYPOTHESIS_REPROPOSED in assessment.signals
    assert assessment.triggered is True


def test_loop_detector_suggests_an_unexhausted_branch():
    state, _ = make_state()
    utterance = "My card is not blocked."
    CorrectionReconciler(state).apply(utterance, CorrectionExtractor().extract(utterance, state))

    branch = LoopDetector(state).next_branch()
    assert branch is not None
    assert branch != "card"


def test_no_branch_left_means_escalate():
    """When every hypothesis is spent, the honest move is a handoff, not another lap."""
    from unloop.resolution.hypotheses import Evidence, EvidenceSource

    state, _ = make_state()
    for hypothesis in list(state.hypotheses.values()):
        state.reject_hypothesis(
            hypothesis.id,
            Evidence(
                id=f"ev_{hypothesis.id}",
                source=EvidenceSource.TOOL,
                summary="checked and ruled out",
                observed_at_version=state.state_version,
                supports=False,
            ),
        )
    assert LoopDetector(state).next_branch() is None


# ---------------------------------------------------------------------------
# Escalation packet (T-E)
# ---------------------------------------------------------------------------


async def test_handoff_packet_carries_the_resolution_state_not_a_transcript():
    state, backend = make_state()

    await backend.get_card_status("demo_customer_001")
    await backend.get_online_transaction_status("demo_customer_001")
    await backend.get_registered_mobile_status("demo_customer_001")
    await backend.get_otp_generation_status("demo_customer_001")
    result, _ = await backend.get_otp_delivery_status("demo_customer_001")

    state.confirm_fact("card_status", "ACTIVE")
    state.confirm_fact("online_transactions", "ENABLED")
    state.confirm_fact("registered_mobile_status", "VERIFIED")
    state.confirm_fact("otp_generation_status", "SUCCESS")

    utterance = "No, my card is not blocked. I used it five minutes ago."
    CorrectionReconciler(state).apply(utterance, CorrectionExtractor().extract(utterance, state))

    from unloop.resolution.hypotheses import Evidence, EvidenceSource

    state.support_hypothesis(
        "OTP_DELIVERY_FAILED",
        Evidence(
            id="ev_delivery",
            source=EvidenceSource.TOOL,
            summary="delivery status FAILED, reason SMS_PROVIDER_FAILURE",
            observed_at_version=state.state_version,
            supports=True,
            detail=result.payload,
        ),
    )

    packet = build_handoff_packet(state)

    confirmed_keys = {c["key"] for c in packet.confirmed}
    assert {"card_status", "otp_generation_status"} <= confirmed_keys

    assert [r["id"] for r in packet.rejected] == ["CARD_BLOCKED"]
    assert packet.rejected[0]["because"]

    assert [o["id"] for o in packet.observed] == ["OTP_DELIVERY_FAILED"]
    assert packet.user_corrections[0]["target"] == "CARD_BLOCKED"
    assert "get_card_status" in packet.attempted
    assert packet.recommended_destination == "OTP and SMS delivery support"

    spoken = packet.to_spoken_summary()
    assert "otp and sms delivery support" in spoken.lower()
    assert "won't need to explain this again" in spoken.lower()


def test_destination_falls_back_when_nothing_is_supported():
    state, _ = make_state()
    assert recommend_destination(state) == "General banking support"


async def test_tool_failure_becomes_an_open_question_not_a_fabrication():
    """T-D: a failed check must be reported as unknown, never guessed."""
    state, backend = make_state("otp_tool_failure")
    result, _ = await backend.get_otp_delivery_status("demo_customer_001")

    assert result.succeeded is False
    assert result.payload == {}
    assert state.recorder.of_type(EventType.TOOL_FAILED)

    packet = build_handoff_packet(state)
    assert any("get_otp_delivery_status" in q for q in packet.open_questions)
    assert not any(o["id"] == "OTP_DELIVERY_FAILED" for o in packet.observed)
