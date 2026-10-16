"""Plan-level endpoints: iCalendar export, CSV export, (future) share links."""

from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.models.enums import CabinClass, TicketStrategyType
from app.services.ics_export import render_plan_ics
from app.services.strategies.base import FlightLeg, StrategyPlan, TicketOffer

router = APIRouter(prefix="/plans", tags=["plans"])


class _LegIn(BaseModel):
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    carrier: str
    flight_number: str
    cabin: CabinClass = CabinClass.ECONOMY
    stops: int = 0


class _TicketIn(BaseModel):
    offer_id: str
    legs: list[_LegIn]
    total_price: int
    currency: str = "TWD"
    fare_class: str | None = None
    baggage_through_checked: bool = True
    issuer: str | None = None


class _PlanIn(BaseModel):
    strategy: TicketStrategyType
    tickets: list[_TicketIn]
    total_cost: int
    currency: str = "TWD"
    pto_days: int = 0
    total_travel_days: int = 0
    explain: str | None = None


def _to_dc(plan_in: _PlanIn) -> StrategyPlan:
    tickets = tuple(
        TicketOffer(
            offer_id=t.offer_id,
            legs=tuple(
                FlightLeg(
                    origin=l.origin,
                    destination=l.destination,
                    departure=l.departure,
                    arrival=l.arrival,
                    carrier=l.carrier,
                    flight_number=l.flight_number,
                    cabin=l.cabin,
                    stops=l.stops,
                )
                for l in t.legs
            ),
            total_price=t.total_price,
            currency=t.currency,
            fare_class=t.fare_class,
            baggage_through_checked=t.baggage_through_checked,
            issuer=t.issuer,
        )
        for t in plan_in.tickets
    )
    return StrategyPlan(
        strategy=plan_in.strategy,
        tickets=tickets,
        total_cost=plan_in.total_cost,
        currency=plan_in.currency,
        pto_days=plan_in.pto_days,
        total_travel_days=plan_in.total_travel_days,
        explain=plan_in.explain,
    )


@router.post("/ics")
def export_plan_as_ics(plan_in: _PlanIn) -> Any:
    if not plan_in.tickets or not any(t.legs for t in plan_in.tickets):
        raise HTTPException(status_code=400, detail="Plan must contain at least one leg")
    ics = render_plan_ics(_to_dc(plan_in))
    filename = f"flight-plan-{plan_in.strategy.value}.ics"
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class _CsvRequest(BaseModel):
    plans: list[_PlanIn]


@router.post("/csv")
def export_plans_as_csv(req: _CsvRequest) -> Any:
    """Flatten N plans into one spreadsheet-friendly table (one row per leg)."""

    if not req.plans:
        raise HTTPException(status_code=400, detail="Need at least one plan")

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "plan_idx", "strategy", "total_cost", "currency",
        "pto_days", "total_travel_days", "explain",
        "ticket_idx", "ticket_offer_id", "ticket_price",
        "leg_idx", "origin", "destination",
        "departure_utc", "arrival_utc",
        "carrier", "flight_number", "cabin", "stops",
    ])
    for pi, p in enumerate(req.plans):
        for ti, t in enumerate(p.tickets):
            for li, leg in enumerate(t.legs):
                writer.writerow([
                    pi, p.strategy.value, p.total_cost, p.currency,
                    p.pto_days, p.total_travel_days, p.explain or "",
                    ti, t.offer_id, t.total_price,
                    li, leg.origin, leg.destination,
                    leg.departure.isoformat(), leg.arrival.isoformat(),
                    leg.carrier, leg.flight_number, leg.cabin.value, leg.stops,
                ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="flight-plans.csv"'},
    )
