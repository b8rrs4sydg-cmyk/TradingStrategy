"""反向票＋倒買法 (two trips) and 外站四腿票 (three trips) over ordered holiday slots."""

from dataclasses import replace
from datetime import date

from app.models.enums import TicketStrategyType as S
from app.models.enums import TripType
from app.schemas.itinerary import CandidateWindowIn, ItineraryRequestIn
from app.services.search import SearchService
from app.services.strategies.back_to_back import FourLegPlanner
from app.services.strategies.reverse import ReverseTicketPlanner
from app.services.strategies.two_trip import TripSlot
from tests.fake_fares import FakeFareProvider

LNY = TripSlot("春節", departs=(date(2027, 2, 4), date(2027, 2, 5), date(2027, 2, 6)),
               returns=(date(2027, 2, 14), date(2027, 2, 15), date(2027, 2, 16)))
QM = TripSlot("清明", departs=(date(2027, 4, 2), date(2027, 4, 3), date(2027, 4, 4)),
              returns=(date(2027, 4, 10), date(2027, 4, 11), date(2027, 4, 12)))
XMAS = TripSlot("聖誕", departs=(date(2027, 12, 22), date(2027, 12, 23), date(2027, 12, 24)),
                returns=(date(2027, 12, 26), date(2027, 12, 27), date(2027, 12, 28)))


def _reverse(destinations=("NRT",)):
    return ReverseTicketPlanner(FakeFareProvider()).plan(
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


def test_entry_and_exit_may_differ_within_the_same_country():
    plans = _reverse(("NRT", "KIX"))
    open_jaw = [p for p in plans if "進" in p.explain]
    assert open_jaw, "大阪進東京出-style plans should be priced too"
    p = open_jaw[0]
    rev = next(t for t, role in zip(p.tickets, p.ticket_roles, strict=True) if role.startswith("反向票"))
    (o1, d1, _), (o2, d2, _) = rev.searched_segments
    assert o1 in ("NRT", "KIX") and d1 == "TPE" and o2 == "TPE" and d2 in ("NRT", "KIX")
    for t in p.tickets:
        if len(t.searched_segments) == 2 and t.searched_segments[0][0] != t.searched_segments[1][1]:
            assert len(t.legs) == 2  # open jaw → priced through search_multi_city


def test_daomai_only_for_japan_thailand_korea():
    assert _reverse(("LHR", "JFK")) == []
    assert all(t.legs[0].destination != "LHR" for p in _reverse(("NRT", "LHR")) for t in p.tickets)


def _four_leg(outer=("HKG", "ICN"), dests=("NRT",), provider=None):
    return FourLegPlanner(provider or FakeFareProvider()).plan(
        trip_p=LNY, trip_q=QM, trip_r=XMAS, outer_stations=list(outer), destinations=list(dests),
    )


def test_four_leg_stitches_three_trips_with_first_and_last_one_ways():
    plans = _four_leg(dests=("LHR",))
    assert plans
    p = next(p for p in plans if p.tickets[1].legs[0].origin == "HKG")
    first, four, last = p.tickets
    assert p.ticket_roles == ("單買初段", "外站四腿票：HKG 出發", "單買最後一段")
    assert len(p.trips) == 3 and p.trip_count == 3
    # 單買初段 is the outbound of trip 1; leg 1 of the 四腿票 is its return
    assert [(leg.origin, leg.destination) for leg in first.legs] == [("TPE", "HKG")]
    assert first.legs[0].departure.date() in LNY.departs
    assert [(leg.origin, leg.destination) for leg in four.legs] == [
        ("HKG", "TPE"), ("TPE", "LHR"), ("LHR", "TPE"), ("TPE", "ICN"),
    ]
    leg1, leg2, leg3, leg4 = four.legs
    assert leg1.departure.date() in LNY.returns     # inside trip 1's window
    assert leg2.departure.date() in QM.departs      # NOT glued to leg 1: another holiday
    assert leg3.departure.date() in QM.returns
    assert leg4.departure.date() in XMAS.departs
    assert [(leg.origin, leg.destination) for leg in last.legs] == [("ICN", "TPE")]
    assert last.legs[0].departure.date() in XMAS.returns
    assert p.total_cost == first.total_price + four.total_price + last.total_price
    codes = {w.code for w in p.warnings}
    assert {"four_leg_first_segment", "four_leg_loop", "four_leg_savings_estimate",
            "four_leg_origin_open_jaw"} <= codes


def test_four_leg_needs_three_slots():
    req = ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP, origins=["TPE"], destinations=["NRT", "LHR"],
        strategies=[S.BACK_TO_BACK_4LEG], back_to_back_outer_stations=["HKG", "ICN"],
        candidate_windows=[
            CandidateWindowIn(holiday_key="lunar_ny", depart=date(2027, 2, 5), return_date=date(2027, 2, 15)),
            CandidateWindowIn(holiday_key="xmas", depart=date(2027, 12, 23), return_date=date(2027, 12, 27)),
        ],
    )
    svc = SearchService(FakeFareProvider())
    _, plans, _ = svc.run(req)
    assert plans == [] and any("三個" in n for n in svc.notices)


def test_four_leg_never_starts_and_ends_in_the_same_country():
    # same-country outstations alone cannot form a plan …
    assert _four_leg(outer=("NRT", "KIX"), dests=("LHR",)) == []
    # … and with a mix, trip B always lands in a third country (not X's, not D's)
    country = {"HKG": "HK", "ICN": "KR", "NRT": "JP", "KIX": "JP", "BKK": "TH"}
    plans = _four_leg(outer=("HKG", "NRT", "KIX", "ICN"), dests=("NRT", "BKK"))
    assert plans
    for p in plans:
        x, d, y = p.tickets[1].legs[0].origin, p.tickets[1].legs[1].destination, p.tickets[1].legs[3].destination
        assert len({country[x], country[d], country[y]}) == 3
        assert p.tickets[0].legs[0].destination == x and p.tickets[2].legs[0].origin == y


def test_best_non_saving_plan_is_kept_and_flagged():
    class Dear(FakeFareProvider):
        def search_multi_city(self, *, segments, adults=1):
            return [replace(o, total_price=o.total_price * 5) for o in super().search_multi_city(segments=segments)]

    plans = _four_leg(dests=("LHR",), provider=Dear())
    assert len(plans) == 1
    assert any(w.code == "no_saving" for w in plans[0].warnings) and "不划算" in plans[0].explain


def test_four_leg_skips_taiwan_and_destination_as_outstation():
    assert _four_leg(outer=("TPE", "KHH", "NRT"), dests=("NRT",)) == []


def test_four_leg_needs_a_provider_that_can_quote_multi_city():
    class NoMultiCity(FakeFareProvider):
        def search_multi_city(self, *, segments, adults=1):
            return []

    assert _four_leg(dests=("LHR",), provider=NoMultiCity()) == []


def test_search_service_labels_plans_with_their_slots():
    req = ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        origins=["TPE"],
        destinations=["NRT", "LHR"],
        strategies=[S.REVERSE, S.BACK_TO_BACK_4LEG],
        back_to_back_outer_stations=["HKG", "ICN"],
        candidate_windows=[
            CandidateWindowIn(holiday_key="lunar_ny", depart=date(2027, 2, 5), return_date=date(2027, 2, 15)),
            CandidateWindowIn(holiday_key="qingming", depart=date(2027, 4, 2), return_date=date(2027, 4, 11)),
            CandidateWindowIn(holiday_key="xmas", depart=date(2027, 12, 23), return_date=date(2027, 12, 27)),
        ],
    )
    svc = SearchService(FakeFareProvider())
    _, plans, _ = svc.run(req)
    assert {p.strategy for p in plans} == {S.REVERSE, S.BACK_TO_BACK_4LEG}
    four_labels = {p.window_label for p in plans if p.strategy is S.BACK_TO_BACK_4LEG}
    assert four_labels == {"春節請 2 休 11 + 清明請 3 休 9 + 聖誕請 2 休 5"}
    assert any("LHR" in n for n in svc.notices)  # 倒買法 is Asia-only
