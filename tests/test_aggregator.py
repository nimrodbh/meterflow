import random

import pytest

from meterflow.native import AggregatorOverflow, CAggregator, PyAggregator, c_available

needs_c = pytest.mark.skipif(not c_available(), reason="C core not built")


def impls():
    out = [PyAggregator]
    if c_available():
        out.append(CAggregator)
    return out


@pytest.mark.parametrize("factory", impls())
def test_totals_per_customer_and_kind(factory):
    agg = factory()
    agg.add(1, 0, 10, 500)
    agg.add(1, 0, 5, 500)
    agg.add(1, 1, 2, 1000)
    agg.add(2, 0, 7, 500)
    rows = {(r.customer, r.kind): r for r in agg.rows()}
    assert len(agg) == 3
    assert (rows[(1, 0)].events, rows[(1, 0)].units, rows[(1, 0)].amount_micro) == (2, 15, 7500)
    assert rows[(1, 1)].amount_micro == 2000
    assert rows[(2, 0)].units == 7


@pytest.mark.parametrize("factory", impls())
def test_overflow_is_reported_not_wrapped(factory):
    agg = factory()
    with pytest.raises(AggregatorOverflow):
        agg.add(1, 0, 2**62, 4)
    agg.add(1, 0, 2**63 - 1, 1)
    with pytest.raises(AggregatorOverflow):
        agg.add(1, 0, 1, 1)


@pytest.mark.parametrize("factory", impls())
def test_clear(factory):
    agg = factory()
    agg.add(1, 0, 1, 1)
    agg.clear()
    assert len(agg) == 0
    assert agg.rows() == []


@needs_c
def test_c_matches_python_on_random_input():
    rng = random.Random(7)
    items = [(rng.randint(0, 5000), rng.randint(0, 2), rng.randint(0, 10_000), rng.randint(0, 50_000)) for _ in range(50_000)]
    py, c = PyAggregator(), CAggregator(initial_capacity=16)  # tiny start forces several table growths
    py.add_many(items)
    c.add_many(items)
    key = lambda r: (r.customer, r.kind)
    assert sorted(py.rows(), key=key) == sorted(c.rows(), key=key)
