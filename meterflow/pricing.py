"""Metered kinds and their unit prices.

Prices are integer micro-dollars per unit (1 USD = 1_000_000 micro), so
rating and invoicing never use floating point.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    id: int
    name: str
    price_micro: int


KINDS: dict[int, Kind] = {
    0: Kind(0, "api_call", 400),  # $0.0004 per call
    1: Kind(1, "storage_gb_hour", 30_000),  # $0.03 per GB-hour
    2: Kind(2, "compute_second", 12_000),  # $0.012 per second
}


def price_micro(kind: int) -> int:
    try:
        return KINDS[kind].price_micro
    except KeyError:
        raise ValueError(f"unknown kind {kind}") from None


def kind_name(kind: int) -> str:
    return KINDS[kind].name if kind in KINDS else f"kind_{kind}"


def micro_to_cents(micro: int) -> int:
    """Round half up to whole cents."""
    return (micro + 5_000) // 10_000


def format_cents(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"
