from app.services.query_plan import prioritize, route_of


def keys(dest, n, kind="ow"):
    return [f"{kind}|TPE|{dest}|2027-04-{d:02d}" for d in range(1, n + 1)]


def test_budget_is_shared_between_routes_not_spent_on_the_first_one():
    plan = [*keys("NRT", 20), *keys("ICN", 20), *keys("BKK", 20)]
    picked = prioritize(plan, 9)
    assert len(picked) == 9
    assert {x for k in picked for x in route_of(k) if x != "TPE"} == {"BKK", "SEL", "TYO"}  # every route got some
    assert plan[:9] != picked


def test_cheap_pages_first_then_the_most_shared_fares():
    counts = {
        "mc|TPE-NRT-2027-04-01|NRT-TPE-2027-04-05": 9,
        "ow|TPE|NRT|2027-04-01": 1,
        "ow|TPE|NRT|2027-04-02": 5,
    }
    assert prioritize(counts, 3)[:2] == ["ow|TPE|NRT|2027-04-02", "ow|TPE|NRT|2027-04-01"]
    assert prioritize(counts, 3)[2].startswith("mc|")


def test_known_fares_are_skipped_and_zero_budget_returns_nothing():
    plan = keys("NRT", 3)
    assert prioritize(plan, 5, known=plan[:2]) == [plan[2]]
    assert prioritize(plan, 0) == []


def test_hnd_and_nrt_count_as_one_route():
    assert route_of("ow|TPE|HND|2027-04-01") == route_of("rt|TPE|NRT|2027-04-01|2027-04-05")


def test_required_queries_counts_what_the_planner_asks():
    from datetime import date

    from app.services.query_plan import required_queries

    def run(rec):
        rec.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 5), return_date=date(2027, 2, 9))
        rec.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 5), return_date=date(2027, 2, 9))
        rec.search(origin="TPE", destination="KIX", departure_date=date(2027, 2, 5))

    keys = required_queries(run)
    assert sorted(keys.values()) == [1, 2]


def _four(x, d, y, day=(2, 4)):
    from datetime import date

    from app.providers.google_flights import fare_key

    m, dd = day
    segs = [
        (x, "TPE", date(2027, m, dd)),
        ("TPE", d, date(2027, m + 1, dd)),
        (d, "TPE", date(2027, m + 1, dd + 6)),
        ("TPE", y, date(2027, 12, dd)),
    ]
    return fare_key(segs), segs


def _prices(segs, *, ow, rt_x=20000, rt_d=20000, rt_y=20000):
    x, d, y = segs[0][0], segs[1][1], segs[3][1]
    p = {f"ow|{o}|{t}|{day.isoformat()}": ow for o, t, day in segs}
    p[f"ow|TPE|{x}|2027-01-20"] = 3000
    p[f"ow|{y}|TPE|2027-12-31"] = 3000
    p[f"rt|TPE|{x}|2027-01-20|{segs[0][2].isoformat()}"] = rt_x
    p[f"rt|TPE|{d}|{segs[1][2].isoformat()}|{segs[2][2].isoformat()}"] = rt_d
    p[f"rt|TPE|{y}|{segs[3][2].isoformat()}|2027-12-31"] = rt_y
    return p


def test_promise_is_floor_over_saving_room():
    from app.services.query_plan import promise

    key, segs = _four("ICN", "LHR", "BKK")
    cheap = promise(key, _prices(segs, ow=5000))  # floor 19000, room 60000 - 6000
    dear = promise(key, _prices(segs, ow=20000))  # floor 76000 > room
    assert cheap is not None and cheap < 1
    assert dear is not None and dear >= 1
    assert promise(key, {}) is None  # nothing known: no opinion


def test_prioritize_asks_hopeful_multi_city_fares_before_hopeless_ones():
    from app.services.query_plan import prioritize, promise

    hopeful, segs_h = _four("ICN", "LHR", "BKK")
    hopeless, segs_n = _four("ICN", "LHR", "BKK", day=(3, 4))
    unknown, _ = _four("ICN", "LHR", "BKK", day=(5, 4))
    prices = {**_prices(segs_h, ow=5000), **_prices(segs_n, ow=20000)}
    order = prioritize(
        [hopeless, unknown, hopeful], 3, promise_of=lambda k: promise(k, prices)
    )
    assert order == [hopeful, unknown, hopeless]
