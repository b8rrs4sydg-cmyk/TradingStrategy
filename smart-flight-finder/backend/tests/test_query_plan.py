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
