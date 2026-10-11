from __future__ import annotations

import re

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .bus import Bus
from .events import Event
from .pricing import format_cents, kind_name, micro_to_cents
from .store import Store

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class EventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=64)
    customer_id: int = Field(ge=0)
    kind: int = Field(ge=0)
    units: int = Field(ge=0)
    ts: int = Field(ge=0)


def create_app(store: Store, bus: Bus | None = None) -> FastAPI:
    app = FastAPI(title="meterflow", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/events", status_code=202)
    def ingest(items: list[EventIn]) -> dict[str, int]:
        if bus is None:
            raise HTTPException(503, "no bus configured")
        if len(items) > 5000:
            raise HTTPException(413, "at most 5000 events per request")
        bus.publish([Event(i.event_id, i.customer_id, i.kind, i.units, i.ts) for i in items])
        return {"accepted": len(items)}

    @app.get("/usage/{customer_id}")
    def usage(customer_id: int, period: str = Query(..., description="YYYY-MM")) -> dict:
        if not PERIOD_RE.match(period):
            raise HTTPException(422, "period must look like 2026-03")
        rows = store.usage(customer_id, period)
        return {
            "customer_id": customer_id,
            "period": period,
            "lines": [{"kind": kind_name(r.kind), "events": r.events, "units": r.units} for r in rows],
        }

    @app.get("/invoice/{customer_id}")
    def invoice(customer_id: int, period: str = Query(..., description="YYYY-MM")) -> dict:
        if not PERIOD_RE.match(period):
            raise HTTPException(422, "period must look like 2026-03")
        rows = store.usage(customer_id, period)
        if not rows:
            raise HTTPException(404, "no usage for that customer and period")
        lines = [
            {
                "kind": kind_name(r.kind),
                "units": r.units,
                "amount": format_cents(micro_to_cents(r.amount_micro)),
            }
            for r in rows
        ]
        total_micro = sum(r.amount_micro for r in rows)
        return {
            "customer_id": customer_id,
            "period": period,
            "currency": "USD",
            "lines": lines,
            "total": format_cents(micro_to_cents(total_micro)),
        }

    return app
