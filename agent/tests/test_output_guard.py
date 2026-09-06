"""T-B: the output guard must block contradicted diagnoses without muting the agent.

The hard part is not blocking "your card is blocked". It is *not* blocking "your card
is not blocked", which is the sentence the agent needs in order to tell the caller
what it ruled out. A guard that fails that is worse than no guard, because it makes
the agent unable to acknowledge the correction at all.
"""

from __future__ import annotations

import pytest

from unloop.observability.events import EventType
from unloop.resolution.hypotheses import build_otp_hypotheses
from unloop.resolution.output_guard import OutputGuard
from unloop.resolution.state import EscalationStatus, ResolutionState
from unloop.tools.types import Subject

from .test_stale_fence import apply_correction


def make_state() -> ResolutionState:
    return ResolutionState(
        issue_type="OTP_NOT_RECEIVED",
        issue_summary="Debit card payment OTP is not being received",
        hypotheses=build_otp_hypotheses(),
    )


# --- assertion detection ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "It looks like your card is blocked.",
        "Your card appears to be blocked, which would explain the missing OTP.",
        "I think the card has been deactivated.",
        "There is a blocked card on this account.",
        # Regression: a negative in a LATER clause must not cancel the claim. An
        # earlier version looked forty characters forward for negation cues and read
        # this as a denial, letting the contradicted diagnosis through.
        "It looks like your card is blocked, which is why the OTP isn't arriving.",
        "Your card is blocked, so the payment won't go through.",
        # Regression: an earlier clause's positive words must not cancel a later
        # claim either.
        "Your number is fine, but the card is blocked.",
    ],
)
def test_card_blocked_assertions_are_detected(text: str):
    state = make_state()
    assert state.get_hypothesis("CARD_BLOCKED").asserted_in(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Your card is not blocked, so that is not the cause.",
        "Your card is showing as active, so a card block doesn't explain this.",
        "The card isn't blocked and online payments are enabled.",
        "I've ruled out a card block.",
        "There is no card block on the account.",
    ],
)
def test_denials_of_card_blocked_are_not_assertions(text: str):
    """The agent must stay able to say what it ruled out."""
    state = make_state()
    assert state.get_hypothesis("CARD_BLOCKED").asserted_in(text) is False


def test_guard_blocks_the_contradicted_diagnosis_but_allows_the_denial():
    state = make_state()
    guard = OutputGuard(state)

    assertion = "It looks like your card is blocked, which is why the OTP isn't arriving."
    assert guard.check(assertion).allowed is True  # not yet rejected

    apply_correction(state)

    blocked = guard.check(assertion, speech_id="sp_x")
    assert blocked.allowed is False
    assert "REJECTED_HYPOTHESIS" in blocked.violations
    assert "ruled out" in blocked.regeneration_hint.lower()

    denial = (
        "Your card is showing as active, so a card block doesn't explain this. "
        "The one-time password was generated, but delivery failed."
    )
    assert guard.check(denial).allowed is True

    events = state.recorder.of_type(EventType.OUTPUT_GUARD_REJECTION)
    assert len(events) == 1
    assert events[0].meta["blocked_hypotheses"] == ["CARD_BLOCKED"]


def test_guard_reports_dependencies_for_the_speech_fence():
    state = make_state()
    asserted, depends_on = OutputGuard(state).analyse(
        "It looks like your card is blocked."
    )
    assert asserted == ("CARD_BLOCKED",)
    assert depends_on == frozenset({Subject.CARD})


# --- conversational hygiene ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Is your issue resolved now?",
        "Did that work for you?",
        "Has the problem been fixed?",
    ],
)
def test_unearned_resolution_checks_are_blocked(text: str):
    """The "is your query resolved?" loop, blocked by rule rather than by request."""
    state = make_state()
    result = OutputGuard(state).check(text)
    assert result.allowed is False
    assert "UNEARNED_RESOLUTION_CHECK" in result.violations


def test_resolution_check_is_allowed_once_something_actually_happened():
    state = make_state()
    state.attempted_actions.append("resend_otp")
    assert OutputGuard(state).check("Did that work?").allowed is True


def test_resolution_check_is_allowed_after_escalation():
    state = make_state()
    state.set_escalation(EscalationStatus.CREATED, reason="no remedy available")
    assert OutputGuard(state).check("Is there anything else you need?").allowed is True


@pytest.mark.parametrize(
    "text",
    [
        "Here is what I found:\n- card active\n- OTP generated",
        "**Card status:** active",
        "1. Check the card\n2. Check delivery",
    ],
)
def test_markdown_never_reaches_tts(text: str):
    result = OutputGuard(make_state()).check(text)
    assert result.allowed is False
    assert "MARKDOWN_IN_SPEECH" in result.violations


def test_internal_machinery_is_not_spoken():
    result = OutputGuard(make_state()).check(
        "My current hypothesis has a confidence score of 0.8."
    )
    assert result.allowed is False
    assert "INTERNAL_LEAK" in result.violations


def test_a_good_support_response_passes_cleanly():
    """The example response from the brief must survive every rule."""
    state = make_state()
    apply_correction(state)
    text = (
        "Your card is showing as active, so a card block doesn't explain this. "
        "The OTP was generated, but delivery failed. I'm checking the delivery service now."
    )
    result = OutputGuard(state).check(text)
    assert result.allowed is True, result.violations
