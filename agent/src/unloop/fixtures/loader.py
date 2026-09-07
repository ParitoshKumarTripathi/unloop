"""Fixture loading and the injectable latency table.

Every number the mock backend returns comes from a JSON file in ``fixtures/``. The
demo controls in the web UI select a fixture and set a delay; they cannot script the
conversation, fabricate a transcript, or force a hypothesis (ADR-009). What a judge
sees on screen is the real engine running against a real fixture.

All data is synthetic. There is no real customer, card, account or phone number
anywhere in this repository.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_FIXTURE = "otp_slow_tool"


def _fixtures_dir() -> Path:
    """Locate ``fixtures/`` by walking up from this file.

    Walking up rather than hard-coding a relative path keeps loading working from the
    repo root, from ``agent/``, from pytest, and from inside the container image,
    where the working directory differs each time.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "fixtures"
        if candidate.is_dir() and any(candidate.glob("*.json")):
            return candidate
    raise FileNotFoundError("could not locate the fixtures/ directory containing scenario JSON")


@dataclass
class Fixture:
    """One deterministic scenario."""

    fixture_id: str
    domain: str
    scenario: str
    label: str
    description: str
    customer: dict[str, Any]
    backend_state: dict[str, Any]
    tool_delays_ms: dict[str, int] = field(default_factory=dict)
    tool_failures: dict[str, str] = field(default_factory=dict)
    expected_resolution: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fixture:
        return cls(
            fixture_id=data["fixture_id"],
            domain=data.get("domain", "banking"),
            scenario=data.get("scenario", data["fixture_id"]),
            label=data.get("label", data["fixture_id"]),
            description=data.get("description", ""),
            customer=data.get("customer", {}),
            backend_state=data.get("backend_state", {}),
            tool_delays_ms=dict(data.get("tool_delays_ms", {})),
            tool_failures=dict(data.get("tool_failures", {})),
            expected_resolution=dict(data.get("expected_resolution", {})),
        )

    @property
    def customer_id(self) -> str:
        return str(self.customer.get("customer_id", "demo_customer_001"))

    @property
    def card_last4(self) -> str:
        return str(self.customer.get("card_last4", "4821"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "domain": self.domain,
            "scenario": self.scenario,
            "label": self.label,
            "description": self.description,
            "customer": self.customer,
            "backend_state": self.backend_state,
            "tool_delays_ms": self.tool_delays_ms,
            "tool_failures": self.tool_failures,
            "expected_resolution": self.expected_resolution,
        }


def load_fixture(fixture_id: str = DEFAULT_FIXTURE) -> Fixture:
    path = _fixtures_dir() / f"{fixture_id}.json"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in _fixtures_dir().glob("*.json")))
        raise FileNotFoundError(f"unknown fixture {fixture_id!r}; available: {available}")
    return Fixture.from_dict(json.loads(path.read_text(encoding="utf-8")))


def available_fixtures(domain: str | None = None) -> list[dict[str, str]]:
    """Fixture ids and labels, for the demo control panel."""
    out: list[dict[str, str]] = []
    for path in sorted(_fixtures_dir().glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        fixture_domain = data.get("domain", "banking")
        if domain is not None and fixture_domain != domain:
            continue
        out.append(
            {
                "fixture_id": data["fixture_id"],
                "domain": fixture_domain,
                "label": data.get("label", data["fixture_id"]),
                "description": data.get("description", ""),
            }
        )
    return out


class LatencyTable:
    """Per-tool injected delays, mutable at runtime for the stress demo.

    Thread-safe because the demo panel writes to it from the room's data channel
    handler while tools read from it on the session loop.
    """

    def __init__(self, initial: dict[str, int] | None = None) -> None:
        self._delays: dict[str, int] = dict(initial or {})
        self._lock = threading.Lock()

    def set(self, tool_name: str, milliseconds: int) -> int:
        """Set the injected delay for one tool. Returns the applied value.

        Clamped to [0, 15000]. The clamp exists so a stray control message cannot
        wedge a live call behind a delay nobody can wait out.
        """
        applied = max(0, min(int(milliseconds), 15_000))
        with self._lock:
            self._delays[tool_name] = applied
        return applied

    def get(self, tool_name: str) -> int:
        with self._lock:
            return self._delays.get(tool_name, 0)

    def clear(self) -> None:
        with self._lock:
            self._delays.clear()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._delays)
