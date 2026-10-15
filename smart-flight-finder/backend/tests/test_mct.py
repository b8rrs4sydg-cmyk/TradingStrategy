from datetime import datetime, timedelta, timezone

from app.models.enums import CabinClass
from app.services.mct import DEFAULT_MCT, check_connection, check_cross_ticket_handoff
from app.services.strategies.base import FlightLeg, RiskLevel, TicketOffer


def _leg(origin, destination, dep, arr) -> FlightLeg:
    return FlightLeg(
        origin=origin,
        destination=destination,
        departure=dep,
        arrival=arr,
        carrier="BR",
        flight_number="BR123",
        cabin=CabinClass.ECONOMY,
    )


def test_same_ticket_international_pass():
    arr = datetime(2027, 2, 5, 10, 0, tzinfo=timezone.utc)
    dep = arr + timedelta(hours=2)
    w = check_connection(
        _leg("XMN", "TPE", arr - timedelta(hours=1), arr),
        _leg("TPE", "NRT", dep, dep + timedelta(hours=3)),
        cross_ticket=False,
    )
    assert w is None


def test_cross_ticket_too_tight_flags_high():
    arr = datetime(2027, 2, 5, 10, 0, tzinfo=timezone.utc)
    dep = arr + timedelta(hours=1)  # only 60min for cross-ticket international
    w = check_connection(
        _leg("XMN", "TPE", arr - timedelta(hours=1), arr),
        _leg("TPE", "NRT", dep, dep + timedelta(hours=3)),
        cross_ticket=True,
    )
    assert w is not None
    assert w.level is RiskLevel.HIGH
    assert w.code == "mct_too_tight"


def test_overlap_detected():
    arr = datetime(2027, 2, 5, 10, 0, tzinfo=timezone.utc)
    dep = arr - timedelta(minutes=15)
    w = check_connection(
        _leg("XMN", "TPE", arr - timedelta(hours=1), arr),
        _leg("TPE", "NRT", dep, dep + timedelta(hours=3)),
        cross_ticket=True,
    )
    assert w and w.code == "mct_negative_overlap"


def test_airport_mismatch():
    arr = datetime(2027, 2, 5, 10, 0, tzinfo=timezone.utc)
    dep = arr + timedelta(hours=4)
    w = check_connection(
        _leg("XMN", "TPE", arr - timedelta(hours=1), arr),
        _leg("TSA", "NRT", dep, dep + timedelta(hours=3)),
        cross_ticket=True,
    )
    assert w and w.code == "connection_airport_mismatch"


def test_cross_ticket_handoff_adds_baggage_warning():
    arr = datetime(2027, 2, 5, 10, 0, tzinfo=timezone.utc)
    dep = arr + timedelta(hours=5)
    inbound = TicketOffer(
        offer_id="A",
        legs=(_leg("XMN", "TPE", arr - timedelta(hours=1), arr),),
        total_price=4200,
        baggage_through_checked=False,
    )
    outbound = TicketOffer(
        offer_id="B",
        legs=(_leg("TPE", "NRT", dep, dep + timedelta(hours=3)),),
        total_price=11000,
    )
    warnings = check_cross_ticket_handoff(inbound, outbound)
    assert any(w.code == "baggage_recheck_required" for w in warnings)
    assert all(w.level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH) for w in warnings)
