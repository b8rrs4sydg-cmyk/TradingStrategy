"""反向票＋倒買法 and 外站四腿票: one purchase, two trips (slot A then slot B)."""

from datetime import date, timedelta

import pytest

from app.models.enums import TicketStrategyType as S
from app.models.enums import TripType
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import CandidateWindowIn, ItineraryRequestIn
from app.services.search import SearchService
from app.services.strategies.back_to_back import FourLegPlanner
from app.services.strategies.reverse import ReverseTicketPlanner
from app.services.strategies.two_trip import TripSlot

LNY = TripSlot("春節", departs=(date(2027, 2, 4), date(2027, 2, 5), date(2027, 2, 6)),
               returns=(date(2027, 2, 14), date(2027, 2, 15), date(2027, 2, 16)))
XMAS = TripSlot("聖誕", departs=(date(2027, 12, 22), date(2027, 12, 23), date(2027, 12, 24)),
                returns=(date(2027, 12, 26), date(2027, 12, 27), date(2027, 12, 28)))


def _reverse(destinations=("NRT",)):
    return ReverseTicketPlanner(StubFlightProvider()).plan(
        trip_a=LNY, trip_b=XMAS, origins=["TPE"], destinations=list(destinations)
    )


def _seg_dates(ticket):
    return [leg.departure.date() for leg in ticket.legs]


def test_daomai_is_wrap_ticket_from_home_plus_reverse_ticket_from_abroad():
    plans = [p for p in _reverse() if "倒買法" in p.explain]
    assert plans, "holiday surge on TW-origin fares should make 倒買法 pay off"
    p = plans[0]
    wrap, rev = p.tickets
    # 包覆票: TPE→NRT at the start of trip A, NRT→TPE at the end of trip B
    assert [(leg.origin, leg.destination) for leg in wrap.legs] == [("TPE", "NRT"), ("NRT", "TPE")]
    assert _seg_dates(wrap)[0] in LNY.departs and _seg_dates(wrap)[1] in XMAS.returns
    # 反向票: NRT→TPE at the end of trip A, TPE→NRT at the start of trip B
    assert [(leg.origin, leg.destination) for leg in rev.legs] == [("NRT", "TPE"), ("TPE", "NRT")]
    assert _seg_dates(rev)[0] in LNY.returns and _seg_dates(rev)[1] in XMAS.departs
    assert p.total_cost == wrap.total_price + rev.total_price
    assert len(p.trips) == 2 and p.trip_count == 2
    assert p.ticket_roles == ("包覆票：TPE 出發", "反向票：NRT 出發")
    assert all(t.searched_segments for t in p.tickets)


def test_bu_tou_wei_variant_uses_two_one_ways_around_the_reverse_ticket():
    plans = [p for p in _reverse() if "補頭尾" in p.explain]
    assert plans
    first, rev, last = plans[0].tickets
    assert (first.legs[0].origin, first.legs[0].destination, len(first.legs)) == ("TPE", "NRT", 1)
    assert (last.legs[0].origin, last.legs[0].destination, len(last.legs)) == ("NRT", "TPE", 1)
    assert rev.legs[0].origin == "NRT"


def test_every_kept_plan_beats_two_ordinary_round_trips():
    for p in _reverse(("NRT", "KIX")):
        saving = next(w for w in p.warnings if w.code == "reverse_savings_estimate")
        assert "省" in saving.message
        assert p.total_cost > 0


def test_different_cities_per_trip_become_open_jaw_multi_city_tickets():
    mixed = [p for p in _reverse(("NRT", "KIX")) if "/ KIX" in p.explain or "/ NRT" in p.explain]
    assert mixed
    rev = next(t for t, role in zip(mixed[0].tickets, mixed[0].ticket_roles, strict=True) if role.startswith("反向票"))
    (o1, d1, _), (o2, d2, _) = rev.searched_segments
    assert o1 != d2  # not a mirrored round trip -> priced as multi-city
    assert o1 in ("NRT", "KIX") and d1 == "TPE" and o2 == "TPE"


def _four_leg(stay=2, outer=("HKG",), dests=("NRT",), provider=None):
    return FourLegPlanner(provider or StubFlightProvider()).plan(
        trip_a=LNY, trip_b=XMAS, outer_stations=list(outer), destinations=list(dests),
        outer_stay_days=stay,
    )


def test_four_leg_is_one_ticket_plus_first_and_last_one_ways():
    plans = _four_leg(dests=("LHR",))
    assert plans
    p = plans[0]
    first, four, last = p.tickets
    assert p.ticket_roles == ("單買初段", "外站四腿票：HKG 出發", "單買最後一段")
    # 單買初段 gets us to the outstation at the start of trip A
    assert [(leg.origin, leg.destination) for leg in first.legs] == [("TPE", "HKG")]
    assert first.legs[0].departure.date() in LNY.departs
    # The 四腿票 itself: X→TPE→D→TPE→X on ONE ticket
    assert [(leg.origin, leg.destination) for leg in four.legs] == [
        ("HKG", "TPE"), ("TPE", "LHR"), ("LHR", "TPE"), ("TPE", "HKG"),
    ]
    leg1, leg2, leg3, leg4 = four.legs
    assert leg1.departure.date() == first.legs[0].departure.date() + timedelta(days=2)
    assert timedelta(0) < leg2.departure - leg1.arrival < timedelta(hours=24)
    assert leg3.departure.date() in LNY.returns     # back home at the end of trip A
    assert leg4.departure.date() in XMAS.departs    # leg 4 starts trip B
    # 單買最後一段 closes the loop at the end of trip B
    assert [(leg.origin, leg.destination) for leg in last.legs] == [("HKG", "TPE")]
    assert last.legs[0].departure.date() in XMAS.returns
    assert p.total_cost == first.total_price + four.total_price + last.total_price
    codes = {w.code for w in p.warnings}
    assert {"four_leg_first_segment", "four_leg_loop", "four_leg_savings_estimate"} <= codes


@pytest.mark.parametrize("stay", [0, 1, 3])
def test_four_leg_outer_stay_days_respected(stay):
    plans = _four_leg(stay=stay, dests=("LHR",))
    assert plans
    for p in plans:
        first, four, _ = p.tickets
        assert (four.legs[0].departure.date() - first.legs[0].departure.date()).days == stay


def test_four_leg_skips_taiwan_and_destination_as_outstation():
    assert _four_leg(outer=("TPE", "KHH", "NRT"), dests=("NRT",)) == []


def test_four_leg_needs_a_provider_that_can_quote_multi_city():
    class NoMultiCity(StubFlightProvider):
        def search_multi_city(self, *, segments, adults=1):
            return []

    assert _four_leg(dests=("LHR",), provider=NoMultiCity()) == []


def test_search_service_labels_pair_plans_with_both_slots():
    req = ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        origins=["TPE"],
        destinations=["NRT", "LHR"],
        strategies=[S.REVERSE, S.BACK_TO_BACK_4LEG],
        back_to_back_outer_stations=["HKG"],
        candidate_windows=[
            CandidateWindowIn(holiday_key="lunar_ny", depart=date(2027, 2, 5), return_date=date(2027, 2, 15)),
            CandidateWindowIn(holiday_key="xmas", depart=date(2027, 12, 23), return_date=date(2027, 12, 27)),
        ],
    )
    svc = SearchService(StubFlightProvider())
    _, plans, _ = svc.run(req)
    assert {p.strategy for p in plans} == {S.REVERSE, S.BACK_TO_BACK_4LEG}
    assert {p.window_label for p in plans} == {"春節請 2 休 11 + 聖誕請 2 休 5"}
    assert svc.notices == []
