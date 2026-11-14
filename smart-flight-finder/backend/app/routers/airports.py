"""GET /airports — catalog behind the origin / destination / 外站 checkboxes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.data.airports import DESTINATIONS, OUTSTATIONS, TW_ORIGINS, Airport

router = APIRouter(tags=["airports"])


class AirportOut(BaseModel):
    code: str
    name_zh: str
    country: str
    group: str


class AirportCatalog(BaseModel):
    origins: list[AirportOut]
    destinations: list[AirportOut]
    outstations: list[AirportOut]


def _out(a: Airport) -> AirportOut:
    return AirportOut(code=a.code, name_zh=a.name_zh, country=a.country, group=a.group)


@router.get("/airports", response_model=AirportCatalog)
def list_airports() -> AirportCatalog:
    return AirportCatalog(
        origins=[_out(a) for a in TW_ORIGINS],
        destinations=[_out(a) for a in DESTINATIONS],
        outstations=[_out(a) for a in OUTSTATIONS],
    )
