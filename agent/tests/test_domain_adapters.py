"""Proof that non-banking scenarios use the same resolution engine invariants."""

from __future__ import annotations

import asyncio

from unloop.agent import ResolutionEngine, UnloopAgent
from unloop.config import AppConfig
from unloop.resolution.hypotheses import HypothesisStatus
from unloop.resolution.stale_fence import FenceVerdict


def test_livekit_tool_surface_is_limited_to_selected_adapter() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="hotel")
    agent = UnloopAgent(engine)
    names = {tool.info.name for tool in agent.tools}

    assert names == {
        "lookup_customer",
        "check_platform_booking",
        "check_hotel_record",
        "reconcile_hotel_booking",
        "check_hotel_availability",
        "change_hotel_dates",
        "change_hotel_guest_count",
        "cancel_hotel_booking",
        "rebook_hotel_booking",
        "list_bookings",
        "get_booking",
        "escalate_to_human",
    }


async def test_banking_agent_can_discover_recent_transaction_and_spoken_id() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="banking")
    agent = UnloopAgent(engine)
    names = {tool.info.name for tool in agent.tools}

    assert {"list_recent_transactions", "get_transaction"} <= names

    await engine.on_user_transcript("What was my last transaction?")
    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "review_transactions"
    recent = await engine.run_tool("list_recent_transactions", limit=1)
    by_spoken_id = await engine.run_tool("get_transaction", transaction_id="five zero one")

    assert "TXN-501" in recent
    assert "Demo Merchant" in recent
    assert "₹1,250" in by_spoken_id
    assert "DECLINED" in by_spoken_id


async def test_banking_transaction_lookup_is_fenced_after_goal_switch() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="banking")
    await engine.on_user_transcript("What was my last transaction?")
    engine.backend.set_mock_tool_delay("list_recent_transactions", 40)

    pending = asyncio.create_task(engine.run_tool("list_recent_transactions", limit=1))
    await asyncio.sleep(0.01)
    await engine.on_user_transcript("Actually, just check whether my debit card is active.")
    message = await pending

    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "verify_card"
    assert engine.state.completed_tools[-1].subject.value == "transaction"
    assert engine.state.completed_tools[-1].stale is True
    assert "out of date" in message
    assert "TXN-501" not in message


async def test_ecommerce_can_report_refund_details_and_resolve_spoken_id() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="ecommerce")
    agent = UnloopAgent(engine)
    assert {"list_orders", "get_order", "list_refunds", "get_refund"} <= {
        tool.info.name for tool in agent.tools
    }

    await engine.on_user_transcript("What is my refund amount?")
    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "view_refund_details"
    listed = await engine.run_tool("list_refunds")
    fetched = await engine.run_tool("get_refund", refund_id="three zero one")

    assert "REF-301" in listed and "₹2,499" in listed
    assert "REF-301" in fetched and "₹2,499" in fetched


async def test_restaurant_can_report_details_without_treating_question_as_change() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="restaurant")
    await engine.on_user_transcript("How many guests are on my reservation?")

    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "view_reservation_details"
    fetched = await engine.run_tool("get_reservation", reservation_id="eight zero one")

    assert "RES-801" in fetched
    assert "party size is 4" in fetched


async def test_salon_can_report_appointment_details_by_spoken_id() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="salon")
    agent = UnloopAgent(engine)
    assert {"list_appointments", "get_appointment"} <= {tool.info.name for tool in agent.tools}

    await engine.on_user_transcript("What time is my appointment?")
    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "view_appointment_details"
    fetched = await engine.run_tool("get_appointment", appointment_id="four zero one")

    assert "APT-401" in fetched
    assert "4:00 PM" in fetched
    assert "Asha" in fetched


async def test_hotel_can_report_booking_id_and_guest_count_without_mutation() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="hotel")
    await engine.on_user_transcript("How many guests are on my hotel booking?")

    assert engine.state.current_goal is not None
    assert engine.state.current_goal.id == "view_booking_details"
    fetched = await engine.run_tool("get_booking", booking_id="two zero one")

    assert "HTL-201" in fetched
    assert "guest count is 2" in fetched
    record = engine.sandbox.get_record("DEMO-1001", "hotel", "booking", "HTL-201")
    assert record is not None and record["guest_count"] == 2


async def test_ecommerce_correction_fences_inflight_refund_result() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="ecommerce")
    engine.backend.set_mock_tool_delay("check_refund_record", 40)

    pending = asyncio.create_task(engine.run_tool("check_refund_record"))
    await asyncio.sleep(0.01)
    await engine.on_user_transcript(
        "No, the refund has not reached my account. Please trace the payment rail."
    )
    tool_message = await pending

    assert engine.state.state_version == 2
    assert (
        engine.state.get_hypothesis("REFUND_ALREADY_RECEIVED").status is HypothesisStatus.REJECTED
    )
    assert engine.state.completed_tools[-1].stale is True
    assert engine.state.completed_tools[-1].fence_verdict == FenceVerdict.SUPERSEDED.value
    assert "out of date" in tool_message
    assert engine.guard.check("The refund has already reached your account.").allowed is False


async def test_restaurant_cross_system_mismatch_changes_shared_strategy_and_rebooks() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="restaurant")
    engine.sandbox.update_record(
        "DEMO-1001",
        "restaurant",
        "reservation",
        {"partner_status": "MISSING"},
        action="TEST_SETUP",
    )
    await engine.on_user_transcript(
        "The restaurant cannot find my reservation even though I have a confirmation."
    )

    platform = await engine.run_tool("check_platform_reservation")
    restaurant = await engine.run_tool("check_restaurant_record")
    action = await engine.run_tool("rebook_reservation")
    escalation = await engine.escalate("restaurant still cannot honour the replacement")

    assert "CONFIRMED" in platform
    assert "MISSING" in restaurant
    assert engine.state.get_hypothesis("PLATFORM_CONFIRMATION_INVALID").is_rejected
    assert (
        engine.state.get_hypothesis("RESERVATION_SYNC_FAILURE").status is HypothesisStatus.SUPPORTED
    )
    assert engine.state.current_strategy == "investigate_reconciliation"
    assert "rebook_reservation" in engine.state.attempted_actions
    assert "REBOOKED" in action
    assert engine.guard.check("Did that resolve the issue?").allowed is True
    assert "Restaurant reservation operations" in escalation
    assert engine.state.case_id is not None


async def test_hotel_correction_uses_adapter_subject_mapping_in_common_output_guard() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="hotel")
    await engine.on_user_transcript(
        "The hotel cannot find my booking even though I have the confirmation."
    )

    rejected = engine.state.get_hypothesis("HOTEL_HAS_BOOKING")
    assert rejected is not None and rejected.is_rejected
    verdict = engine.guard.check("The hotel already has your booking.")
    assert verdict.allowed is False
    assert [subject.value for subject in verdict.depends_on] == ["partner_record"]
    loop = engine.loop_detector.assess()
    assert loop.triggered is True
    assert loop.suggested_branch != "hotel_record"
