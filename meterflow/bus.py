"""Message bus between producers and the consumer.

Delivery is at-least-once: a message stays pending until `ack`. The consumer
makes that safe by deduplicating on event_id (see store.py).
"""

from __future__ import annotations

from collections import deque
from typing import Protocol

from .events import Event


class Bus(Protocol):
    def publish(self, events: list[Event]) -> None: ...
    def read(self, max_messages: int, block_ms: int = 0) -> list[tuple[str, Event]]: ...
    def ack(self, message_ids: list[str]) -> None: ...


class InMemoryBus:
    """Single-process bus for tests and local runs."""

    def __init__(self) -> None:
        self._queue: deque[tuple[str, Event]] = deque()
        self._pending: dict[str, Event] = {}
        self._next = 0

    def publish(self, events: list[Event]) -> None:
        for e in events:
            self._next += 1
            self._queue.append((str(self._next), e))

    def read(self, max_messages: int, block_ms: int = 0) -> list[tuple[str, Event]]:
        out: list[tuple[str, Event]] = []
        while self._queue and len(out) < max_messages:
            mid, e = self._queue.popleft()
            self._pending[mid] = e
            out.append((mid, e))
        return out

    def ack(self, message_ids: list[str]) -> None:
        for mid in message_ids:
            self._pending.pop(mid, None)

    def redeliver_pending(self) -> int:
        """Simulate a crash before ack: pending messages go back on the queue."""
        n = len(self._pending)
        for mid, e in list(self._pending.items()):
            self._queue.appendleft((mid, e))
        self._pending.clear()
        return n


class RedisBus:
    """Redis Streams with a consumer group."""

    def __init__(self, url: str, stream: str = "usage", group: str = "billing", consumer: str = "c1") -> None:
        import redis

        self._r = redis.Redis.from_url(url, decode_responses=True)
        self._stream, self._group, self._consumer = stream, group, consumer
        try:
            self._r.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(self, events: list[Event]) -> None:
        pipe = self._r.pipeline()
        for e in events:
            pipe.xadd(self._stream, {"e": e.to_json()})
        pipe.execute()

    def read(self, max_messages: int, block_ms: int = 0) -> list[tuple[str, Event]]:
        # Pending (delivered but unacked) messages first, so a crashed batch is retried.
        resp = self._r.xreadgroup(self._group, self._consumer, {self._stream: "0"}, count=max_messages)
        entries = resp[0][1] if resp else []
        if not entries:
            resp = self._r.xreadgroup(
                self._group, self._consumer, {self._stream: ">"}, count=max_messages, block=block_ms or None
            )
            entries = resp[0][1] if resp else []
        return [(mid, Event.from_json(fields["e"])) for mid, fields in entries]

    def ack(self, message_ids: list[str]) -> None:
        if message_ids:
            self._r.xack(self._stream, self._group, *message_ids)
