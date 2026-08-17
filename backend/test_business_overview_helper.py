"""
Pure-logic tests for business_overview_helper (no DB / network).

Run inside the backend container:
    python -m pytest -q backend/test_business_overview_helper.py   (if pytest is installed)
    python backend/test_business_overview_helper.py                (plain asserts)
"""
from datetime import date

import business_overview_helper as bov


TODAY = date(2026, 8, 17)  # a Monday


def test_resolve_preset_week_and_month_boundaries():
    assert bov.resolve_preset("today", TODAY) == (TODAY, TODAY)
    assert bov.resolve_preset("yesterday", TODAY) == (date(2026, 8, 16), date(2026, 8, 16))
    # Monday-start weeks: on a Monday "this_week" is just today
    assert bov.resolve_preset("this_week", TODAY) == (date(2026, 8, 17), date(2026, 8, 17))
    assert bov.resolve_preset("last_week", TODAY) == (date(2026, 8, 10), date(2026, 8, 16))
    wed = date(2026, 8, 19)
    assert bov.resolve_preset("this_week", wed) == (date(2026, 8, 17), wed)
    assert bov.resolve_preset("this_month", TODAY) == (date(2026, 8, 1), TODAY)
    assert bov.resolve_preset("last_month", TODAY) == (date(2026, 7, 1), date(2026, 7, 31))
    assert bov.resolve_preset("last_7_days", TODAY) == (date(2026, 8, 11), TODAY)
    assert bov.resolve_preset("last_30_days", TODAY) == (date(2026, 7, 19), TODAY)
    assert bov.resolve_preset("this_year", TODAY) == (date(2026, 1, 1), TODAY)
    # January edge: last_month rolls over the year
    assert bov.resolve_preset("last_month", date(2026, 1, 5)) == (date(2025, 12, 1), date(2025, 12, 31))


def test_previous_period_same_length_and_whole_month_rule():
    # arbitrary 7-day window -> the 7 days immediately before
    assert bov.previous_period(date(2026, 8, 11), date(2026, 8, 17)) == (date(2026, 8, 4), date(2026, 8, 10))
    # single day -> the day before
    assert bov.previous_period(TODAY, TODAY) == (date(2026, 8, 16), date(2026, 8, 16))
    # whole month -> whole previous month (31 vs 30 days is fine)
    assert bov.previous_period(date(2026, 8, 1), date(2026, 8, 31)) == (date(2026, 7, 1), date(2026, 7, 31))
    assert bov.previous_period(date(2026, 3, 1), date(2026, 3, 31)) == (date(2026, 2, 1), date(2026, 2, 28))
    # two whole months -> the two before
    assert bov.previous_period(date(2026, 7, 1), date(2026, 8, 31)) == (date(2026, 5, 1), date(2026, 6, 30))
    # month-to-date is NOT whole month -> same length before
    assert bov.previous_period(date(2026, 8, 1), date(2026, 8, 17)) == (date(2026, 7, 15), date(2026, 7, 31))
    # whole year of months across the year boundary
    assert bov.previous_period(date(2025, 8, 1), date(2026, 7, 31)) == (date(2024, 8, 1), date(2025, 7, 31))


def test_resolve_period_validation():
    p = bov.resolve_period("2026-08-01", "2026-08-31", None, "America/Chicago", today=TODAY)
    assert (p.start, p.end, p.prev_start, p.prev_end) == (date(2026, 8, 1), date(2026, 8, 31), date(2026, 7, 1), date(2026, 7, 31))
    assert p.days == 31 and p.end_excl == "2026-09-01" and p.preset is None
    p2 = bov.resolve_period(None, None, "last_week", "UTC", today=TODAY)
    assert p2.preset == "last_week" and p2.as_dict()["today"] == "2026-08-17"
    for args in (("2026-08-10", "2026-08-01"), ("2020-01-01", "2026-08-01"), ("2026-08-01", None)):
        try:
            bov.resolve_period(args[0], args[1], None, "UTC", today=TODAY)
            assert False, "expected ValueError"
        except ValueError:
            pass
    try:
        bov.resolve_period(None, None, "fortnight", "UTC", today=TODAY)
        assert False
    except ValueError:
        pass


def test_iter_buckets_clipping_and_labels():
    weeks = bov.iter_buckets(date(2026, 7, 1), date(2026, 7, 31), "week")
    assert weeks[0] == (date(2026, 6, 29), date(2026, 7, 1), date(2026, 7, 5))
    assert weeks[-1] == (date(2026, 7, 27), date(2026, 7, 27), date(2026, 7, 31))
    assert len(weeks) == 5
    months = bov.iter_buckets(date(2026, 8, 15), date(2026, 10, 3), "month")
    assert [m[0] for m in months] == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
    assert months[0][1] == date(2026, 8, 15) and months[-1][2] == date(2026, 10, 3)
    days = bov.iter_buckets(TODAY, TODAY, "day")
    assert days == [(TODAY, TODAY, TODAY)]
    assert bov.bucket_label(date(2026, 8, 3), "day") == "Aug 3"
    assert bov.bucket_label(date(2026, 8, 3), "week") == "Wk of Aug 3"
    assert bov.bucket_label(date(2026, 8, 3), "month") == "Aug 2026"


def test_rollup_daily_zero_fills_and_sums():
    daily = {
        date(2026, 8, 3): {"revenue": 10.0, "cost": 4.0},
        date(2026, 8, 4): {"revenue": 5.0, "cost": 1.0},
        date(2026, 8, 12): {"revenue": 7.0, "cost": 2.0},
        date(2026, 9, 1): {"revenue": 99.0, "cost": 1.0},  # outside range
    }
    out = bov.rollup_daily(daily, date(2026, 8, 1), date(2026, 8, 14), "week", ["revenue", "cost"])
    assert [b["key"] for b in out] == ["2026-07-27", "2026-08-03", "2026-08-10"]
    assert out[0]["values"] == {"revenue": 0.0, "cost": 0.0}
    assert out[1]["values"] == {"revenue": 15.0, "cost": 5.0}
    assert out[2]["values"] == {"revenue": 7.0, "cost": 2.0}
    assert out[0]["start"] == "2026-08-01" and out[-1]["end"] == "2026-08-14"
    tot = bov.sum_daily(daily, date(2026, 8, 1), date(2026, 8, 31), ["revenue"])
    assert tot == {"revenue": 22.0}


def test_pct_change_and_margin():
    assert bov.pct_change(110, 100) == 10.0
    assert bov.pct_change(90, 100) == -10.0
    assert bov.pct_change(50, 0) is None
    assert bov.pct_change(None, 5) is None
    assert bov.margin_pct(200, 150) == 25.0
    assert bov.margin_pct(0, 10) is None
    rt = bov.range_totals({"a": 10, "b": 0}, {"a": 8})
    assert rt == {"current": {"a": 10.0, "b": 0.0}, "previous": {"a": 8.0, "b": 0.0},
                  "change_pct": {"a": 25.0, "b": None}}


def test_totals_math_and_unknown_cost():
    t = bov._totals_dict(100, 60, 5, 3, 10, 1.0)
    assert (t["profit"], t["margin_pct"], t["net_revenue"]) == (40.0, 40.0, 95.0)
    unknown = bov._totals_dict(100, 0, 0, 3, 10, 0.0)   # units sold, no cost known
    assert unknown["margin_pct"] is None
    merged = bov.add_totals(t, unknown)
    assert merged["revenue"] == 200.0 and merged["cost"] == 60.0 and merged["cost_coverage"] == 0.5
    ch = bov.totals_change(t, bov._totals_dict(80, 60, 0, 2, 8, 1.0))
    assert ch["revenue"] == 25.0 and ch["margin_pct"] == 15.0  # points, not %


def test_aging_bucket_and_excl_clause():
    assert [bov.aging_bucket(d) for d in (0, 1, 2, 3, 4, 40, None)] == ["0-1", "0-1", "2-3", "2-3", "4+", "4+", None]
    sql, params = bov._excl_clause(["ACME", " ", None, "Beta"])
    assert sql == " AND (h.BusinessName IS NULL OR (h.BusinessName NOT IN (?,?)))" and params == ["ACME", "Beta"]
    assert bov._excl_clause([]) == ("", [])


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    names = [n for n in dir(mod) if n.startswith("test_")]
    for n in names:
        getattr(mod, n)()
        print(f"ok  {n}")
    print(f"{len(names)} tests passed")
