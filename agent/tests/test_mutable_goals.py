"""Mutable goals are independent of the selected synthetic demo preset."""

from __future__ import annotations

import asyncio

from unloop.agent import ResolutionEngine
from unloop.config import AppConfig
from unloop.resolution.stale_fence import FenceVerdict, SpeechTicket
from unloop.resolution.state import EscalationStatus


async def test_restaurant_goal_change_fences_lookup_and_preserves_time() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="restaurant")
    engine.backend.set_mock_tool_delay("check_restaurant_availability", 40)

    assert engine.state.current_goal is None
    assert engine.state.hypotheses == {}
    assert engine.adapter.opening_line == "Restaurant support. How can I help you today?"
    assert "missing" not in engine.state.issue_summary.lower()

    await engine.on_user_transcript("Can you move my reservation to 7 PM?")
    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "reschedule_reservation"
    move_version = engine.state.state_version

    old_lookup = asyncio.create_task(
        engine.run_tool("check_restaurant_availability", requested_time="7 PM")
    )
    await asyncio.sleep(0.01)
    await engine.on_user_transcript(
        "Actually keep it at 8 PM. Just change it from four people to six."
    )

    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "change_party_size"
    assert engine.state.current_goal.parameters["party_size"] == 6
    assert engine.state.state_version == move_version + 1
    assert "out of date" in await old_lookup
    stale = engine.state.completed_tools[-1]
    assert stale.stale is True
    assert stale.fence_verdict == FenceVerdict.SUPERSEDED.value
    assert stale.triggered_speech is False

    result = await engine.run_tool("change_restaurant_party_size", party_size=6)
    record = engine.sandbox.get_record("DEMO-1001", "restaurant", "reservation")
    assert "remains at 8:00 PM" in result
    assert "party size is now 6" in result
    assert record["time"] == "8:00 PM"
    assert record["party_size"] == 6


async def test_goal_change_fences_speech_even_without_hypothesis_words() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="restaurant")
    await engine.on_user_transcript("Move my reservation to 7 PM")
    ticket = SpeechTicket(
        speech_id="old-move-answer",
        state_version=engine.state.state_version,
        text="Seven P M is available, so I will move it.",
        goal_id="reschedule_reservation",
    )
    await engine.on_user_transcript("Keep it at 8 PM and change the party to six people")

    decision = engine.fence.authorize_speech(ticket)
    assert decision.allowed is False
    assert decision.blocking_rule == "SUPERSEDED_GOAL_SPEECH"


async def test_ecommerce_goal_can_replace_refund_preset_with_order_cancellation() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="ecommerce")
    engine.backend.set_mock_tool_delay("trace_refund_payment", 40)
    assert engine.state.current_goal is None
    assert "awaiting customer intent" in engine.state.issue_summary

    await engine.on_user_transcript("Please trace my missing refund")
    pending = asyncio.create_task(engine.run_tool("trace_refund_payment"))
    await asyncio.sleep(0.01)
    await engine.on_user_transcript("Actually, cancel my order instead")

    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "cancel_order"
    assert "out of date" in await pending
    action = await engine.run_tool("cancel_order")

    # The refund preset remains backend seed data; it never owns the goal.
    assert engine.fixture.fixture_id == "ecommerce_refund_missing"
    assert engine.sandbox.get_record("DEMO-1001", "ecommerce", "order")["status"] == "CANCELLED"
    assert "CANCELLED" in action


async def test_pronoun_rebook_followups_replace_previous_goal_across_domains() -> None:
    cases = (
        ("restaurant", "Check my reservation", "rebook_reservation"),
        ("salon", "Check my appointment", "rebook_appointment"),
        ("hotel", "Check my booking", "rebook_booking"),
    )
    for domain, first_request, expected_goal in cases:
        engine = ResolutionEngine(AppConfig(), domain_id=domain)
        await engine.on_user_transcript(first_request)
        previous_version = engine.state.state_version

        await engine.on_user_transcript("Actually, book it again")

        assert engine.state.current_goal is not None
        assert engine.state.current_goal.id == expected_goal
        assert engine.state.state_version == previous_version + 1


async def test_plural_hotel_guest_followup_changes_goal_and_parameter_name() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="hotel")
    await engine.on_user_transcript("Check my booking")

    await engine.on_user_transcript("Actually, change it to three guests")

    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "change_guest_count"
    assert engine.state.current_goal.parameters == {"guest_count": 3}
    result = await engine.run_tool("change_hotel_guest_count", guest_count=3)
    assert "guest count is now 3" in result


async def test_supported_but_non_automated_requests_enter_structured_escalation() -> None:
    cases = (
        ("banking", "Please block my debit card", "manage_card_security"),
        ("ecommerce", "Please replace my damaged headphones", "replace_order_item"),
    )
    for domain, request, expected_goal in cases:
        engine = ResolutionEngine(AppConfig(), domain_id=domain)

        await engine.on_user_transcript(request)

        assert engine.state.current_goal is not None
        assert engine.state.current_goal.id == expected_goal
        assert engine.state.escalation_status is EscalationStatus.RECOMMENDED
        assert engine.state.current_strategy == "escalate"
        handoff = await engine.escalate("requires a human-operated support workflow")
        assert engine.adapter.escalation_destination in handoff
        assert engine.state.escalation_status is EscalationStatus.CREATED
