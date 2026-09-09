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
        "escalate_to_human",
    }


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
