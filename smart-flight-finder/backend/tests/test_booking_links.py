from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlparse

from app.models.enums import CabinClass
from app.services.booking_links import booking_links
from app.services.strategies.base import FlightLeg, TicketOffer


def _leg(o, d, y, m, day, h=9):
    dep = datetime(y, m, day, h, tzinfo=UTC)
    return FlightLeg(o, d, dep, dep.replace(hour=h + 3), "BR", "BR100")


def _by_source(t, **kw):
    return {b.source: b.url for b in booking_links(t, **kw)}


def test_round_trip_links_carry_route_dates_pax_cabin():
    t = TicketOffer("x", (_leg("TPE", "NRT", 2027, 2, 5), _leg("NRT", "TPE", 2027, 2, 15)), 20000)
    urls = _by_source(t, adults=2, cabin=CabinClass.BUSINESS)
    assert set(urls) == {"trip_com", "google_flights", "skyscanner"}

    trip = urlparse(urls["trip_com"])
    q = {k: v[0] for k, v in parse_qs(trip.query).items()}
    assert trip.netloc == "www.trip.com"
    assert q["dcity"] == "tpe" and q["acity"] == "nrt"
    assert q["ddate"] == "2027-02-05" and q["rdate"] == "2027-02-15"
    assert q["triptype"] == "rt" and q["class"] == "c" and q["quantity"] == "2"

    assert "/tpe/nrt/270205/270215/" in urls["skyscanner"]
    assert "adultsv2=2" in urls["skyscanner"] and "cabinclass=business" in urls["skyscanner"]

    g = unquote(urls["google_flights"])
    assert "from TPE to NRT on 2027-02-05 through 2027-02-15" in g and "2 adults business" in g


def test_one_way_links():
    t = TicketOffer("x", (_leg("XMN", "TPE", 2027, 2, 4),), 4000)
    urls = _by_source(t)
    q = parse_qs(urlparse(urls["trip_com"]).query)
    assert q["triptype"] == ["ow"] and "rdate" not in q
    assert "/xmn/tpe/270204/?" in urls["skyscanner"]


def test_connecting_round_trip_finds_turnaround():
    legs = (
        _leg("TPE", "HKG", 2027, 2, 5, 8),
        _leg("HKG", "BKK", 2027, 2, 5, 13),
        _leg("BKK", "HKG", 2027, 2, 12, 8),
        _leg("HKG", "TPE", 2027, 2, 12, 14),
    )
    q = parse_qs(urlparse(_by_source(TicketOffer("x", legs, 1))["trip_com"]).query)
    assert q["acity"] == ["bkk"] and q["rdate"] == ["2027-02-12"]


# Produced by fast-flights' generated flights_pb2 (Info message) for the same
# itinerary — our hand-rolled encoder must stay byte-identical.
FOUR_LEG_TFS = "GhoSCjIwMjctMDItMDdqBRIDSEtHcgUSA1RQRRoaEgoyMDI3LTAyLTA3agUSA1RQRXIFEgNOUlQaGhIKMjAyNy0wMi0xNWoFEgNOUlRyBRIDVFBFGhoSCjIwMjctMTItMjJqBRIDVFBFcgUSA0hLR0IBAUgBmAED"


def _four_leg_ticket():
    from dataclasses import replace
    from datetime import date

    segs = (("HKG", "TPE", date(2027, 2, 7)), ("TPE", "NRT", date(2027, 2, 7)),
            ("NRT", "TPE", date(2027, 2, 15)), ("TPE", "HKG", date(2027, 12, 22)))
    legs = tuple(_leg(o, d, day.year, day.month, day.day) for o, d, day in segs)
    return replace(TicketOffer("mc", legs, 1), searched_segments=segs)


def test_multi_city_ticket_gets_multi_city_links_on_every_site():
    from app.services.booking_links import google_flights_tfs

    t = _four_leg_ticket()
    links = {b.source: b for b in booking_links(t)}
    assert all("多段" in b.label for b in links.values())

    assert google_flights_tfs(t.searched_segments, adults=1, cabin=CabinClass.ECONOMY) == FOUR_LEG_TFS
    g = urlparse(links["google_flights"].url)
    assert unquote(parse_qs(g.query, keep_blank_values=True)["tfs"][0]) == FOUR_LEG_TFS or         parse_qs(g.query)["tfs"][0] == FOUR_LEG_TFS

    q = {k: v[0] for k, v in parse_qs(urlparse(links["trip_com"].url).query).items()}
    assert q["triptype"] == "mt"
    assert q["dcity"] == "hkg,tpe,nrt,tpe" and q["acity"] == "tpe,nrt,tpe,hkg"
    assert q["ddate"] == "2027-02-07,2027-02-07,2027-02-15,2027-12-22"

    assert "/transport/d/hkg/2027-02-07/tpe/tpe/2027-02-07/nrt/nrt/2027-02-15/tpe/tpe/2027-12-22/hkg/" in links["skyscanner"].url


def test_mirrored_two_segment_ticket_from_daomai_still_uses_multi_city():
    from dataclasses import replace
    from datetime import date

    segs = (("NRT", "TPE", date(2027, 2, 14)), ("TPE", "NRT", date(2027, 12, 23)))
    t = replace(TicketOffer("rt", (_leg("NRT", "TPE", 2027, 2, 14), _leg("TPE", "NRT", 2027, 12, 23)), 1),
                searched_segments=segs)
    assert {b.label for b in booking_links(t)} == {"Trip.com 多段", "Google Flights 多段", "Skyscanner 多段"}
