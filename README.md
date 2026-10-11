# meterflow

A small usage-metering and billing pipeline. Events come in, get queued, are aggregated per customer and month, and turn into invoices through a REST API. The service is Python; the hot aggregation loop is a C library.

```
generator / POST /events ──> bus (Redis Streams) ──> consumer ──> SQLite ──> GET /usage, GET /invoice
                                                       │
                                                  C aggregator (ctypes)
```

## What is in here

| Part | What it does |
|---|---|
| `core/aggregator.c` | Open-addressing hash table keyed by (customer, kind). Integer micro-dollar money, overflow-checked arithmetic, no floats. Unit tests run under UBSan. |
| `meterflow/native.py` | ctypes binding plus a pure Python twin. A test feeds both 50,000 random events and requires identical output. |
| `meterflow/bus.py` | In-memory bus for tests, Redis Streams with a consumer group for real runs. At-least-once delivery. |
| `meterflow/store.py`, `consumer.py` | Dedupe by event id and write usage and ids in one transaction, so redelivery never double-bills. |
| `meterflow/api.py` | FastAPI: `POST /events`, `GET /usage/{customer}`, `GET /invoice/{customer}`, `GET /health`. |

## Run it

```bash
# tests (C core is built first so the C-vs-Python test runs)
make -C core test && make -C core build/libaggregator.so
pip install -e ".[dev]"
pytest -q

# whole stack
docker compose up --build -d
docker compose --profile demo run --rm generator
curl "localhost:8000/invoice/42?period=2026-02"

# benchmark
python -m meterflow.cli bench --n 1000000
```

## Numbers

1,000,000 events, 10,000 customers, one core, measured on a laptop (Windows, Python 3.12):

| Path | Events per second |
|---|---|
| Pure Python | 1.6 million |
| C, called with Python tuples (includes packing them) | 2.4 million |
| C core on pre-packed columns | 59 million |

The C loop is about 37x faster than Python, but end to end the gain is only 1.5x, because turning Python objects into arrays costs more than the aggregation itself. The next step is to feed the consumer pre-packed batches; this is why the benchmark reports both numbers.

## Design choices worth a look

- **Exactly-once accounting on top of at-least-once delivery.** The bus may redeliver. Event ids and totals are committed in one transaction, and `tests/test_consumer.py` covers redelivery, duplicates inside a batch, and a crash before the ack.
- **Money never touches a float.** Prices are integer micro-dollars; overflow is detected in C and Python alike and raised, not wrapped.
- **Two implementations, one test.** The C code is trusted because a Python reference agrees with it on random input.

## Not done yet

- Postgres instead of SQLite, and more than one consumer (the unique-id guard is there, the retry path is not load-tested).
- Prometheus metrics and a Grafana dashboard.
- Deployed demo.
