from meterflow.bus import InMemoryBus
from meterflow.consumer import Consumer
from meterflow.events import Event, generate
from meterflow.native import PyAggregator
from meterflow.pricing import price_micro
from meterflow.store import Store

JAN = 1_767_225_600  # 2026-01-01 UTC
FEB = JAN + 31 * 24 * 3600


def make(batch=100):
    bus, store = InMemoryBus(), Store()
    return bus, store, Consumer(bus, store, PyAggregator(), batch_size=batch)


def expected_total(events):
    return sum(e.units * price_micro(e.kind) for e in events)


def test_end_to_end_totals_match_independent_calculation():
    bus, store, consumer = make(batch=250)
    events = list(generate(5000, customers=50, seed=3))
    bus.publish(events)
    consumer.drain()
    assert store.totals() == (len(events), expected_total(events))


def test_redelivered_batch_is_not_double_counted():
    bus, store, consumer = make()
    events = [Event(f"e{i}", 1, 0, 10, JAN + i) for i in range(20)]
    bus.publish(events)
    consumer.run_once()
    assert store.totals()[0] == 20
    # Pretend the ack was lost: the same messages come back.
    bus.publish(events)
    res = consumer.run_once()
    assert res.duplicates == 20 and res.applied == 0
    assert store.totals()[0] == 20


def test_duplicate_inside_one_batch_counts_once():
    bus, store, consumer = make()
    e = Event("same", 1, 0, 5, JAN)
    bus.publish([e, e, e])
    consumer.run_once()
    assert store.totals() == (1, 5 * price_micro(0))


def test_batch_spanning_two_months_lands_in_two_periods():
    bus, store, consumer = make()
    bus.publish([Event("a", 9, 0, 1, JAN), Event("b", 9, 0, 1, FEB)])
    consumer.run_once()
    assert store.usage(9, "2026-01")[0].events == 1
    assert store.usage(9, "2026-02")[0].events == 1


def test_bad_events_are_rejected_and_acked():
    bus, _, consumer = make()
    bus.publish([Event("a", 1, 99, 1, JAN), Event("b", 1, 0, -4, JAN), Event("c", 1, 0, 2, JAN)])
    res = consumer.run_once()
    assert (res.rejected, res.applied) == (2, 1)
    assert bus.read(10) == []  # nothing left pending or queued


def test_unacked_messages_are_redelivered_after_a_crash():
    bus, store, consumer = make()
    events = [Event(f"x{i}", 2, 0, 1, JAN) for i in range(10)]
    bus.publish(events)
    msgs = bus.read(100)  # consumer read them, then "crashed" before applying or acking
    assert len(msgs) == 10
    bus.redeliver_pending()
    consumer.drain()
    assert store.totals()[0] == 10
