"""Closed registry used by LiveKit dispatch and the demo selector."""

from __future__ import annotations

from .banking import BankingAdapter
from .base import DomainAdapter
from .ecommerce import EcommerceAdapter
from .hotel import HotelAdapter
from .restaurant import RestaurantAdapter
from .salon import SalonAdapter

_DOMAINS: dict[str, DomainAdapter] = {
    adapter.domain_id: adapter
    for adapter in (
        BankingAdapter(),
        EcommerceAdapter(),
        RestaurantAdapter(),
        SalonAdapter(),
        HotelAdapter(),
    )
}


def get_domain(domain_id: str | None) -> DomainAdapter:
    """Return a known adapter, defaulting safely to the judged banking scenario."""
    return _DOMAINS.get((domain_id or "banking").strip().lower(), _DOMAINS["banking"])


def available_domains() -> list[dict[str, str]]:
    return [
        {
            "id": adapter.domain_id,
            "label": adapter.label,
            "issue": adapter.issue_summary,
            "fixture_id": adapter.default_fixture,
        }
        for adapter in _DOMAINS.values()
    ]
