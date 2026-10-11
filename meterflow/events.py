from __future__ import annotations

import json
import random
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Event:
    event_id: str
    customer_id: int
    kind: int
    units: int
    ts: int  # unix seconds, UTC

    def period(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=UTC).strftime("%Y-%m")

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def from_json(raw: str) -> Event:
        d = json.loads(raw)
        return Event(str(d["event_id"]), int(d["customer_id"]), int(d["kind"]), int(d["units"]), int(d["ts"]))


def generate(
    n: int,
    customers: int = 1000,
    start_ts: int = 1_767_225_600,  # 2026-01-01 UTC
    span_seconds: int = 90 * 24 * 3600,
    seed: int | None = None,
) -> Iterator[Event]:
    """Deterministic (when seeded) stream of usage events."""
    rng = random.Random(seed)
    for _ in range(n):
        kind = rng.choices([0, 1, 2], weights=[80, 5, 15])[0]
        units = {0: rng.randint(1, 20), 1: rng.randint(1, 500), 2: rng.randint(1, 3600)}[kind]
        yield Event(
            event_id=str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            customer_id=rng.randint(1, customers),
            kind=kind,
            units=units,
            ts=start_ts + rng.randint(0, span_seconds),
        )
