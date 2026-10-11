"""Command line entry points.

    python -m meterflow.cli generate --n 100000        # push synthetic events to the bus
    python -m meterflow.cli consume                    # run the consumer loop
    python -m meterflow.cli bench --n 1000000          # C vs Python aggregator
    python -m meterflow.cli serve                      # run the HTTP API
"""

from __future__ import annotations

import argparse
import os
import time
from array import array

from .bus import Bus, InMemoryBus, RedisBus
from .consumer import Consumer
from .events import generate
from .native import CAggregator, PyAggregator, c_available, make_aggregator
from .pricing import price_micro
from .store import Store


def make_bus() -> Bus:
    url = os.environ.get("REDIS_URL")
    return RedisBus(url) if url else InMemoryBus()


def cmd_generate(args: argparse.Namespace) -> None:
    bus = make_bus()
    batch = []
    for e in generate(args.n, customers=args.customers, seed=args.seed):
        batch.append(e)
        if len(batch) == 2000:
            bus.publish(batch)
            batch = []
    if batch:
        bus.publish(batch)
    print(f"published {args.n} events")


def cmd_consume(args: argparse.Namespace) -> None:
    store = Store(os.environ.get("DB_PATH", "meterflow.db"))
    consumer = Consumer(make_bus(), store, make_aggregator(), batch_size=args.batch)
    print("consumer started")
    while True:
        r = consumer.run_once(block_ms=2000)
        if r.read:
            print(f"batch read={r.read} applied={r.applied} dup={r.duplicates} rejected={r.rejected}", flush=True)


def cmd_bench(args: argparse.Namespace) -> None:
    items = [(e.customer_id, e.kind, e.units, price_micro(e.kind)) for e in generate(args.n, customers=args.customers, seed=1)]
    results = {}

    def run(name: str, agg, feed) -> None:
        t0 = time.perf_counter()
        feed(agg)
        dt = time.perf_counter() - t0
        results[name] = dt
        print(f"{name:26s} {args.n / dt:>14,.0f} events/s  ({dt:.3f}s, {len(agg)} groups)")

    run("python", PyAggregator(), lambda a: a.add_many(items))
    if not c_available():
        print("c: not built, skipping")
        return
    run("c, tuples (incl. packing)", CAggregator(), lambda a: a.add_many(items))
    cols = (
        array("Q", (i[0] for i in items)),
        array("I", (i[1] for i in items)),
        array("q", (i[2] for i in items)),
        array("q", (i[3] for i in items)),
    )
    run("c, packed columns (core)", CAggregator(), lambda a: a.add_columns(*cols))
    print(f"speedup end to end: {results['python'] / results['c, tuples (incl. packing)']:.1f}x")
    print(f"speedup of the core:  {results['python'] / results['c, packed columns (core)']:.1f}x")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .api import create_app

    app = create_app(Store(os.environ.get("DB_PATH", "meterflow.db")), make_bus())
    uvicorn.run(app, host="0.0.0.0", port=args.port)


def main() -> None:
    p = argparse.ArgumentParser(prog="meterflow")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("--n", type=int, default=100_000)
    g.add_argument("--customers", type=int, default=1000)
    g.add_argument("--seed", type=int, default=None)
    g.set_defaults(fn=cmd_generate)

    c = sub.add_parser("consume")
    c.add_argument("--batch", type=int, default=1000)
    c.set_defaults(fn=cmd_consume)

    b = sub.add_parser("bench")
    b.add_argument("--n", type=int, default=1_000_000)
    b.add_argument("--customers", type=int, default=10_000)
    b.set_defaults(fn=cmd_bench)

    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
