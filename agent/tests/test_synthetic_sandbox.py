"""Authoritative SQLite sandbox and stale-write guarantees."""

from __future__ import annotations

import asyncio

import pytest

from unloop.agent import ResolutionEngine
from unloop.config import AppConfig
from unloop.sandbox import DEMO_CUSTOMER_ID, SyntheticSupportSandbox


async def test_restaurant_unrelated_goals_mutate_one_persistent_record(tmp_path) -> None:
    path = tmp_path / "support.sqlite3"
    sandbox = SyntheticSupportSandbox(path)
    engine = ResolutionEngine(AppConfig(), domain_id="restaurant", sandbox=sandbox)

    original = sandbox.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")
    assert original["reservation_id"] == "RES-801"
    assert original["time"] == "8:00 PM"
    assert original["party_size"] == 4

    await engine.on_user_transcript("Move my reservation to 7 PM")
    await engine.run_tool("reschedule_restaurant_reservation", new_time="7:00 PM")
    await engine.on_user_transcript("Now change it to six people")
    await engine.run_tool("change_restaurant_party_size", party_size=6)

    reopened = SyntheticSupportSandbox(path)
    changed = reopened.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")
    assert changed["time"] == "7:00 PM"
    assert changed["party_size"] == 6
    assert len(reopened.recent_changes("restaurant")) == 2

    reopened.reset_demo_data()
    reset = reopened.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")
    assert reset["time"] == "8:00 PM"
    assert reset["party_size"] == 4


async def test_superseded_write_never_mutates_sqlite(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    engine = ResolutionEngine(AppConfig(), domain_id="restaurant", sandbox=sandbox)
    engine.backend.set_mock_tool_delay("reschedule_restaurant_reservation", 40)

    await engine.on_user_transcript("Move my reservation to 7 PM")
    obsolete = asyncio.create_task(
        engine.run_tool("reschedule_restaurant_reservation", new_time="7:00 PM")
    )
    await asyncio.sleep(0.01)
    await engine.on_user_transcript("Actually keep it at 8 and make it six people")

    assert "out of date" in await obsolete
    record = sandbox.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")
    assert record["time"] == "8:00 PM"
    assert sandbox.recent_changes("restaurant") == []

    await engine.run_tool("change_restaurant_party_size", party_size=6)
    final = sandbox.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")
    assert final["time"] == "8:00 PM"
    assert final["party_size"] == 6


async def test_restaurant_reschedule_updates_date_and_time_separately(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    engine = ResolutionEngine(AppConfig(), domain_id="restaurant", sandbox=sandbox)

    await engine.on_user_transcript("Prepone my reservation to September 11 at 6 PM")
    availability = await engine.run_tool(
        "check_restaurant_availability",
        requested_date="2026-09-11",
        requested_time="6 PM",
    )
    assert "available" in availability

    result = await engine.run_tool(
        "reschedule_restaurant_reservation",
        new_date="2026-09-11",
        new_time="6 PM",
    )
    assert "2026-09-11 at 6:00 PM" in result
    record = sandbox.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")
    assert record["date"] == "2026-09-11"
    assert record["time"] == "6:00 PM"

    changed_fields = {
        change["field"] for change in sandbox.recent_changes("restaurant")[0]["fields"]
    }
    assert changed_fields == {"date", "time"}


async def test_combined_datetime_is_split_before_restaurant_write(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    engine = ResolutionEngine(AppConfig(), domain_id="restaurant", sandbox=sandbox)

    await engine.on_user_transcript("Prepone it to September 11 at 6 PM")
    await engine.run_tool("reschedule_restaurant_reservation", new_time="2026-09-11 6:00 PM")

    record = sandbox.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")
    assert record["date"] == "2026-09-11"
    assert record["time"] == "6:00 PM"


def test_sandbox_rejects_a_date_embedded_in_a_time_field(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")

    with pytest.raises(ValueError, match="only a clock time"):
        sandbox.update_record(
            DEMO_CUSTOMER_ID,
            "restaurant",
            "reservation",
            {"time": "2026-09-11 6:00 PM"},
        )

    record = sandbox.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")
    assert record["date"] == "2026-09-12"
    assert record["time"] == "8:00 PM"


@pytest.mark.parametrize(
    ("domain", "record_type", "changes", "message"),
    [
        ("banking", "card", {"online_transactions": "4821"}, "online_transactions"),
        ("ecommerce", "order", {"status": "₹2,499"}, "status"),
        ("restaurant", "reservation", {"party_size": "six"}, "whole number"),
        ("salon", "appointment", {"time": "2026-09-14 3:00 PM"}, "clock time"),
        (
            "salon",
            "appointment",
            {"service": "2026-09-14 3:00 PM"},
            "service name",
        ),
        ("hotel", "booking", {"guest_count": 0}, "between 1 and 20"),
        ("hotel", "booking", {"check_out": "2026-09-19"}, "after check-in"),
        ("hotel", "booking", {"check_out": "2026-99-99"}, "valid calendar date"),
        ("banking", "card", {"last4": "2026-09-11"}, "four digits"),
        ("banking", "otp", {"otp_event_id": "OTP-999"}, "cannot be changed"),
        ("banking", "transaction", {"amount": "tomorrow at six"}, "amount"),
        ("ecommerce", "refund", {"unexpected": "value"}, "unknown record fields"),
    ],
)
def test_authoritative_sandbox_rejects_cross_field_corruption_in_every_domain(
    tmp_path, domain, record_type, changes, message
) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    before = sandbox.get_record(DEMO_CUSTOMER_ID, domain, record_type)

    with pytest.raises(ValueError, match=message):
        sandbox.update_record(DEMO_CUSTOMER_ID, domain, record_type, changes)

    assert sandbox.get_record(DEMO_CUSTOMER_ID, domain, record_type) == before
    assert sandbox.recent_changes(domain) == []


async def test_salon_combined_datetime_is_split_and_hotel_partial_dates_are_preserved(
    tmp_path,
) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    salon = ResolutionEngine(AppConfig(), domain_id="salon", sandbox=sandbox)

    await salon.on_user_transcript("Prepone my appointment to September 14 at 3 PM")
    result = await salon.run_tool("reschedule_appointment", new_time="2026-09-14 3:00 PM")
    assert "2026-09-14 at 3:00 PM" in result
    appointment = sandbox.get_record(DEMO_CUSTOMER_ID, "salon", "appointment")
    assert appointment["date"] == "2026-09-14"
    assert appointment["time"] == "3:00 PM"

    hotel = ResolutionEngine(AppConfig(), domain_id="hotel", sandbox=sandbox)
    await hotel.on_user_transcript("Extend my hotel stay through September 23")
    result = await hotel.run_tool("change_hotel_dates", check_out="2026-09-23")
    assert "2026-09-20 through 2026-09-23" in result
    booking = sandbox.get_record(DEMO_CUSTOMER_ID, "hotel", "booking")
    assert booking["check_in"] == "2026-09-20"
    assert booking["check_out"] == "2026-09-23"


async def test_invalid_tool_arguments_fail_without_mutating_authoritative_state(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    hotel = ResolutionEngine(AppConfig(), domain_id="hotel", sandbox=sandbox)
    before = sandbox.get_record(DEMO_CUSTOMER_ID, "hotel", "booking")

    await hotel.on_user_transcript("Change my checkout date")
    result = await hotel.run_tool("change_hotel_dates", check_out="September 19 at 6 PM")

    assert "did not complete" in result
    assert sandbox.get_record(DEMO_CUSTOMER_ID, "hotel", "booking") == before
    assert sandbox.recent_changes("hotel") == []


async def test_unavailable_schedule_never_changes_restaurant_record(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    restaurant = ResolutionEngine(AppConfig(), domain_id="restaurant", sandbox=sandbox)
    before = sandbox.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")

    await restaurant.on_user_transcript("Move my reservation to September 11 at 5 PM")
    result = await restaurant.run_tool(
        "reschedule_restaurant_reservation",
        new_date="2026-09-11",
        new_time="5:00 PM",
    )

    assert "unavailable" in result.lower()
    assert sandbox.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation") == before
    assert sandbox.recent_changes("restaurant") == []


async def test_salon_has_deterministic_business_hour_availability_across_dates(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    salon = ResolutionEngine(AppConfig(), domain_id="salon", sandbox=sandbox)

    await salon.on_user_transcript("Can you move my appointment to September 18 at 5 PM?")
    result = await salon.run_tool(
        "check_salon_availability",
        requested_date="2026-09-18",
        requested_time="5 PM",
    )

    assert "2026-09-18 at 5:00 PM is available" in result


async def test_restaurant_has_useful_multi_day_availability(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    restaurant = ResolutionEngine(AppConfig(), domain_id="restaurant", sandbox=sandbox)

    await restaurant.on_user_transcript("Move my reservation to September 18 at 9 PM")
    result = await restaurant.run_tool(
        "check_restaurant_availability",
        requested_date="2026-09-18",
        requested_time="9 PM",
    )

    assert "2026-09-18 at 9:00 PM is available" in result


async def test_unavailable_salon_time_returns_real_same_day_alternatives(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    salon = ResolutionEngine(AppConfig(), domain_id="salon", sandbox=sandbox)

    await salon.on_user_transcript("Can you move my appointment to September 18 at 8 PM?")
    result = await salon.run_tool(
        "check_salon_availability",
        requested_date="2026-09-18",
        requested_time="8 PM",
    )

    assert "8:00 PM is unavailable" in result
    assert "Available times that day include" in result


def test_reopening_existing_sandbox_refreshes_availability_without_resetting_records(
    tmp_path,
) -> None:
    path = tmp_path / "support.sqlite3"
    original = SyntheticSupportSandbox(path)
    original.update_record(
        DEMO_CUSTOMER_ID,
        "restaurant",
        "reservation",
        {"party_size": 6},
    )
    with original._db:
        original._db.execute("DELETE FROM availability")

    reopened = SyntheticSupportSandbox(path)

    assert reopened.get_record(DEMO_CUSTOMER_ID, "restaurant", "reservation")["party_size"] == 6
    assert (
        reopened.check_availability("salon", "Demo Studio", "2026-09-18", "5:00 PM")["availability"]
        == "AVAILABLE"
    )


async def test_hotel_inventory_is_authoritative_and_unavailable_dates_do_not_mutate(
    tmp_path,
) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")
    hotel = ResolutionEngine(AppConfig(), domain_id="hotel", sandbox=sandbox)
    before = sandbox.get_record(DEMO_CUSTOMER_ID, "hotel", "booking")

    await hotel.on_user_transcript("Extend my hotel stay")
    available = await hotel.run_tool(
        "check_hotel_availability", check_in="2026-09-20", check_out="2026-09-23"
    )
    unavailable = await hotel.run_tool(
        "change_hotel_dates", check_in="2026-11-15", check_out="2026-11-17"
    )

    assert "is available" in available
    assert "is unavailable" in unavailable
    assert sandbox.get_record(DEMO_CUSTOMER_ID, "hotel", "booking") == before
    assert sandbox.recent_changes("hotel") == []


async def test_idempotent_actions_report_already_done_without_extra_writes(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")

    restaurant = ResolutionEngine(AppConfig(), domain_id="restaurant", sandbox=sandbox)
    await restaurant.on_user_transcript("Keep my reservation at 8 PM")
    restaurant_result = await restaurant.run_tool(
        "reschedule_restaurant_reservation", new_time="8 PM"
    )

    hotel = ResolutionEngine(AppConfig(), domain_id="hotel", sandbox=sandbox)
    await hotel.on_user_transcript("Keep it at two guests")
    hotel_result = await hotel.run_tool("change_hotel_guest_count", guest_count=2)

    ecommerce = ResolutionEngine(AppConfig(), domain_id="ecommerce", sandbox=sandbox)
    await ecommerce.on_user_transcript("Return my order")
    await ecommerce.run_tool("request_return")
    ecommerce_result = await ecommerce.run_tool("request_return")

    assert "already in place" in restaurant_result
    assert "already in place" in hotel_result
    assert "already in place" in ecommerce_result
    assert sandbox.recent_changes("restaurant") == []
    assert sandbox.recent_changes("hotel") == []
    assert len(sandbox.recent_changes("ecommerce")) == 1


async def test_repeated_evidence_gated_actions_are_safe_idempotent_successes(tmp_path) -> None:
    sandbox = SyntheticSupportSandbox(tmp_path / "support.sqlite3")

    banking = ResolutionEngine(AppConfig(), domain_id="banking", sandbox=sandbox)
    await banking.on_user_transcript("My OTP was not received")
    await banking.run_tool("get_otp_delivery_status")
    await banking.run_tool("resend_otp")
    banking_result = await banking.run_tool("resend_otp")
    otp = sandbox.get_record(DEMO_CUSTOMER_ID, "banking", "otp")

    ecommerce = ResolutionEngine(AppConfig(), domain_id="ecommerce", sandbox=sandbox)
    await ecommerce.on_user_transcript("My refund has not arrived")
    await ecommerce.run_tool("check_refund_record")
    await ecommerce.run_tool("trace_refund_payment")
    await ecommerce.run_tool("reissue_refund")
    ecommerce_result = await ecommerce.run_tool("reissue_refund")

    assert "already in place" in banking_result
    assert otp["delivery_status"] == "DELIVERED"
    assert otp["failure_reason"] is None
    assert "already in place" in ecommerce_result
    assert len(sandbox.recent_changes("banking")) == 1
    assert len(sandbox.recent_changes("ecommerce")) == 1
