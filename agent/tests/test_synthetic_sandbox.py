"""Authoritative SQLite sandbox and stale-write guarantees."""

from __future__ import annotations

import asyncio

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
