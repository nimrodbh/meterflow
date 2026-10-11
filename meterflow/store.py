"""SQLite store for aggregated usage plus the set of processed event ids.

`apply` writes the usage rows and the event ids in ONE transaction, so a crash
can never leave counted-but-unrecorded events (or the reverse). Redelivered
events are then recognised by `unseen` and skipped, which turns the bus's
at-least-once delivery into exactly-once accounting.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable

from .native import Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    customer_id  INTEGER NOT NULL,
    period       TEXT    NOT NULL,
    kind         INTEGER NOT NULL,
    events       INTEGER NOT NULL,
    units        INTEGER NOT NULL,
    amount_micro INTEGER NOT NULL,
    PRIMARY KEY (customer_id, period, kind)
);
CREATE TABLE IF NOT EXISTS seen_events (event_id TEXT PRIMARY KEY);
"""


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def unseen(self, event_ids: list[str]) -> set[str]:
        """Return the ids that have not been applied yet."""
        if not event_ids:
            return set()
        with self._lock:
            seen: set[str] = set()
            for i in range(0, len(event_ids), 500):
                chunk = event_ids[i : i + 500]
                marks = ",".join("?" * len(chunk))
                seen.update(
                    r[0] for r in self._db.execute(f"SELECT event_id FROM seen_events WHERE event_id IN ({marks})", chunk)
                )
        return set(event_ids) - seen

    def apply(self, rows_by_period: dict[str, list[Row]], event_ids: Iterable[str]) -> None:
        with self._lock, self._db:  # one transaction
            self._db.executemany("INSERT INTO seen_events(event_id) VALUES (?)", ((i,) for i in event_ids))
            for period, rows in rows_by_period.items():
                self._db.executemany(
                    """
                    INSERT INTO usage(customer_id, period, kind, events, units, amount_micro)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(customer_id, period, kind) DO UPDATE SET
                        events = events + excluded.events,
                        units = units + excluded.units,
                        amount_micro = amount_micro + excluded.amount_micro
                    """,
                    ((r.customer, period, r.kind, r.events, r.units, r.amount_micro) for r in rows),
                )

    def usage(self, customer_id: int, period: str) -> list[Row]:
        with self._lock:
            cur = self._db.execute(
                "SELECT customer_id, kind, events, units, amount_micro FROM usage "
                "WHERE customer_id = ? AND period = ? ORDER BY kind",
                (customer_id, period),
            )
            return [Row(*r) for r in cur.fetchall()]

    def totals(self) -> tuple[int, int]:
        """(total events, total amount_micro) across everything. Used by tests."""
        with self._lock:
            ev, amt = self._db.execute("SELECT COALESCE(SUM(events),0), COALESCE(SUM(amount_micro),0) FROM usage").fetchone()
            return int(ev), int(amt)
