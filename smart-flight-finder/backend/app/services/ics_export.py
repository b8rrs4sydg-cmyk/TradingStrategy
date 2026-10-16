"""Render a :class:`StrategyPlan` as an iCalendar (``.ics``) payload.

Each leg becomes one VEVENT so a traveller can see flights alongside their
usual calendar. We hand-roll RFC 5545 instead of pulling an iCal dep because
the surface we need is tiny and vendor adapters never agree on edge cases.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import StringIO

from app.services.strategies.base import FlightLeg, StrategyPlan

_PROD_ID = "-//Smart Flight Finder//EN"


def render_plan_ics(plan: StrategyPlan, *, base_url: str | None = None) -> str:
    now_utc = datetime.now(UTC)

    buf = StringIO()
    _write(buf, "BEGIN:VCALENDAR")
    _write(buf, "VERSION:2.0")
    _write(buf, f"PRODID:{_PROD_ID}")
    _write(buf, "CALSCALE:GREGORIAN")
    _write(buf, "METHOD:PUBLISH")

    for ti, ticket in enumerate(plan.tickets):
        for li, leg in enumerate(ticket.legs):
            uid = _uid(plan, ti, li, leg)
            _write(buf, "BEGIN:VEVENT")
            _write(buf, f"UID:{uid}")
            _write(buf, f"DTSTAMP:{_fmt_utc(now_utc)}")
            _write(buf, f"DTSTART:{_fmt_utc(leg.departure)}")
            _write(buf, f"DTEND:{_fmt_utc(leg.arrival)}")
            _write(buf, f"SUMMARY:{_escape(_summary(leg))}")
            _write(buf, f"LOCATION:{_escape(f'{leg.origin} → {leg.destination}')}")
            _write(buf, f"DESCRIPTION:{_escape(_description(plan, ticket, leg))}")
            if base_url:
                _write(buf, f"URL:{base_url}")
            _write(buf, "END:VEVENT")

    _write(buf, "END:VCALENDAR")
    return buf.getvalue()


def _summary(leg: FlightLeg) -> str:
    return f"✈ {leg.carrier}{leg.flight_number[len(leg.carrier):] or leg.flight_number} {leg.origin}→{leg.destination}"


def _description(plan: StrategyPlan, ticket, leg: FlightLeg) -> str:
    parts = [
        f"Strategy: {plan.strategy.value}",
        f"Ticket: {ticket.offer_id} ({ticket.currency} {ticket.total_price:,})",
        f"Flight: {leg.carrier}{leg.flight_number} · {leg.cabin.value} · {leg.stops} stops",
    ]
    if plan.explain:
        parts.append(f"Plan: {plan.explain}")
    return "\\n".join(parts)


def _uid(plan: StrategyPlan, ti: int, li: int, leg: FlightLeg) -> str:
    seed = f"{plan.strategy.value}:{ti}:{li}:{leg.departure.isoformat()}:{leg.origin}:{leg.destination}"
    return hashlib.sha1(seed.encode()).hexdigest() + "@smart-flight-finder"


def _fmt_utc(dt: datetime) -> str:
    aware = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def _write(buf: StringIO, line: str) -> None:
    """RFC 5545 §3.1 line folding: 75 octets then CRLF + leading space."""

    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        buf.write(line)
        buf.write("\r\n")
        return
    # Fold at char boundaries after 72 bytes to be safe with multi-byte chars.
    chunk = []
    size = 0
    first = True
    for ch in line:
        ch_size = len(ch.encode("utf-8"))
        if size + ch_size > 72:
            buf.write("".join(chunk))
            buf.write("\r\n ")
            chunk, size = [], 0
            first = False
        chunk.append(ch)
        size += ch_size
    buf.write("".join(chunk))
    buf.write("\r\n")
    if first:
        pass
