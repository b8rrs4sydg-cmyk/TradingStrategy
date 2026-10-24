from datetime import date

from app.models.enums import DateWindowRole, TripType
from app.schemas.itinerary import DateWindowIn
from app.services.date_matrix import (
    expand_window,
    iter_date_combos,
    matrix_cardinality,
)


def test_expand_simple_window():
    w = DateWindowIn(
        role=DateWindowRole.OUTBOUND,
        anchor_date=date(2027, 2, 5),
        flex_before=1,
        flex_after=2,
    )
    exp = expand_window(w)
    assert exp.candidates == (
        date(2027, 2, 4),
        date(2027, 2, 5),
        date(2027, 2, 6),
        date(2027, 2, 7),
    )


def test_expand_weekend_only_filter():
    w = DateWindowIn(
        role=DateWindowRole.OUTBOUND,
        anchor_date=date(2027, 2, 5),
        flex_before=3,
        flex_after=3,
        allow_weekend_only=True,
    )
    exp = expand_window(w)
    # 2027-02-05 is Fri; weekend-only drops Fri. Sat/Sun around = 02-06, 02-07
    assert date(2027, 2, 6) in exp.candidates  # Sat
    assert date(2027, 2, 7) in exp.candidates  # Sun
    assert date(2027, 2, 5) not in exp.candidates


def test_cartesian_cardinality():
    out = expand_window(
        DateWindowIn(role=DateWindowRole.OUTBOUND, anchor_date=date(2027, 2, 5),
                     flex_before=2, flex_after=2)
    )
    ret = expand_window(
        DateWindowIn(role=DateWindowRole.RETURN, anchor_date=date(2027, 2, 11),
                     flex_before=1, flex_after=1)
    )
    assert matrix_cardinality([out, ret]) == 5 * 3


def test_round_trip_pruning_requires_return_after_outbound():
    out = expand_window(
        DateWindowIn(role=DateWindowRole.OUTBOUND, anchor_date=date(2027, 2, 5),
                     flex_before=0, flex_after=1)
    )
    ret = expand_window(
        DateWindowIn(role=DateWindowRole.RETURN, anchor_date=date(2027, 2, 6),
                     flex_before=0, flex_after=1)
    )
    combos = list(iter_date_combos([out, ret], trip_type=TripType.ROUND_TRIP,
                                   min_days_abroad=1))
    for combo in combos:
        assert (combo[1] - combo[0]).days >= 1


def test_multi_city_strict_order():
    seg1 = expand_window(
        DateWindowIn(role=DateWindowRole.SEGMENT, anchor_date=date(2027, 2, 5),
                     sequence=0, flex_before=0, flex_after=1)
    )
    seg2 = expand_window(
        DateWindowIn(role=DateWindowRole.SEGMENT, anchor_date=date(2027, 2, 7),
                     sequence=1, flex_before=0, flex_after=1)
    )
    combos = list(iter_date_combos([seg1, seg2], trip_type=TripType.MULTI_CITY))
    assert combos
    for c in combos:
        assert c[0] < c[1]


def test_max_days_abroad_cap():
    out = expand_window(
        DateWindowIn(role=DateWindowRole.OUTBOUND, anchor_date=date(2027, 2, 5),
                     flex_after=0)
    )
    ret = expand_window(
        DateWindowIn(role=DateWindowRole.RETURN, anchor_date=date(2027, 2, 20),
                     flex_after=0)
    )
    combos = list(iter_date_combos([out, ret], trip_type=TripType.ROUND_TRIP,
                                   min_days_abroad=1, max_days_abroad=10))
    assert not combos  # 15 days > cap

    with_cap = list(iter_date_combos([out, ret], trip_type=TripType.ROUND_TRIP,
                                     min_days_abroad=1, max_days_abroad=30))
    assert len(with_cap) == 1
