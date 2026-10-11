from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from .bus import Bus
from .events import Event
from .native import Aggregator, Row
from .pricing import price_micro
from .store import Store


@dataclass
class BatchResult:
    read: int = 0
    applied: int = 0
    duplicates: int = 0
    rejected: int = 0


class Consumer:
    def __init__(self, bus: Bus, store: Store, aggregator: Aggregator, batch_size: int = 1000) -> None:
        self.bus, self.store, self.agg, self.batch_size = bus, store, aggregator, batch_size

    def run_once(self, block_ms: int = 0) -> BatchResult:
        msgs = self.bus.read(self.batch_size, block_ms)
        res = BatchResult(read=len(msgs))
        if not msgs:
            return res

        # Drop unknown kinds and negative units: they can never be billed, so acking them is right.
        valid: list[Event] = []
        for _, e in msgs:
            try:
                price_micro(e.kind)
            except ValueError:
                res.rejected += 1
                continue
            if e.units < 0:
                res.rejected += 1
                continue
            valid.append(e)

        # Drop events already applied (redelivery) and repeats inside this batch.
        fresh_ids = self.store.unseen([e.event_id for e in valid])
        fresh: list[Event] = []
        taken: set[str] = set()
        for e in valid:
            if e.event_id in fresh_ids and e.event_id not in taken:
                taken.add(e.event_id)
                fresh.append(e)
        res.duplicates = len(valid) - len(fresh)
        res.applied = len(fresh)

        by_period: dict[str, list[Event]] = defaultdict(list)
        for e in fresh:
            by_period[e.period()].append(e)

        rows_by_period: dict[str, list[Row]] = {}
        for period, events in by_period.items():
            self.agg.clear()
            self.agg.add_many((e.customer_id, e.kind, e.units, price_micro(e.kind)) for e in events)
            rows_by_period[period] = self.agg.rows()
        self.agg.clear()

        try:
            self.store.apply(rows_by_period, taken)
        except sqlite3.IntegrityError:
            # Another consumer applied some of these ids between our check and our write.
            # Nothing was committed, so leave the messages un-acked and let them be redelivered.
            res.applied = 0
            return res

        self.bus.ack([mid for mid, _ in msgs])
        return res

    def drain(self) -> BatchResult:
        total = BatchResult()
        while True:
            r = self.run_once()
            if r.read == 0:
                return total
            total.read += r.read
            total.applied += r.applied
            total.duplicates += r.duplicates
            total.rejected += r.rejected
