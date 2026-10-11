from fastapi.testclient import TestClient

from meterflow.api import create_app
from meterflow.bus import InMemoryBus
from meterflow.consumer import Consumer
from meterflow.native import PyAggregator
from meterflow.store import Store

JAN = 1_767_225_600


def setup():
    bus, store = InMemoryBus(), Store()
    return TestClient(create_app(store, bus)), Consumer(bus, store, PyAggregator())


def post(client, items):
    return client.post("/events", json=items)


def test_ingest_then_invoice():
    client, consumer = setup()
    r = post(
        client,
        [
            {"event_id": "1", "customer_id": 7, "kind": 0, "units": 1000, "ts": JAN},  # 1000 * 0.0004 = 0.40
            {"event_id": "2", "customer_id": 7, "kind": 2, "units": 100, "ts": JAN + 5},  # 100 * 0.012 = 1.20
        ],
    )
    assert r.status_code == 202 and r.json() == {"accepted": 2}
    consumer.drain()

    inv = client.get("/invoice/7", params={"period": "2026-01"}).json()
    assert inv["total"] == "1.60"
    assert [(l["kind"], l["amount"]) for l in inv["lines"]] == [("api_call", "0.40"), ("compute_second", "1.20")]

    usage = client.get("/usage/7", params={"period": "2026-01"}).json()
    assert usage["lines"][0] == {"kind": "api_call", "events": 1, "units": 1000}


def test_unknown_customer_has_no_invoice():
    client, _ = setup()
    assert client.get("/invoice/1", params={"period": "2026-01"}).status_code == 404


def test_bad_period_and_bad_payload_are_rejected():
    client, _ = setup()
    assert client.get("/usage/1", params={"period": "2026-13"}).status_code == 422
    assert post(client, [{"event_id": "1", "customer_id": 1, "kind": 0, "units": -5, "ts": JAN}]).status_code == 422


def test_health():
    client, _ = setup()
    assert client.get("/health").json() == {"status": "ok"}
