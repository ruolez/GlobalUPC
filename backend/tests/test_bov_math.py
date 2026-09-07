"""
Pure-math unit tests for business_overview_helper (no database, no network).

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import business_overview_helper as bov  # noqa: E402


class TotalsDictTests(unittest.TestCase):
    def test_backoffice_defaults_derive_gross_and_net_from_returns(self):
        t = bov._totals_dict(revenue=1000.0, cost=600.0, returns=50.0, orders=3, units=10.0,
                             cost_coverage=1.0, shipping=25.0)
        self.assertEqual(t, {
            "revenue": 1000.0, "gross_revenue": 1000.0, "cost": 600.0,
            "profit": 375.0, "shipping_cost": 25.0, "shipping_collected": 0.0,
            "margin_pct": 40.0, "returns": 50.0, "net_revenue": 950.0,
            "orders": 3, "units": 10.0, "cost_coverage": 1.0,
        })

    def test_shopify_explicit_gross_and_net_carry_line_basis(self):
        t = bov._totals_dict(revenue=27719.34, cost=22857.26, returns=384.54, orders=18, units=1217.0,
                             cost_coverage=0.9901, shipping_collected=615.55,
                             gross_revenue=28103.88, net_revenue=27719.34)
        self.assertEqual((t["revenue"], t["gross_revenue"], t["net_revenue"], t["returns"]),
                         (27719.34, 28103.88, 27719.34, 384.54))
        self.assertEqual(t["profit"], round(27719.34 - 22857.26 + 615.55, 2))
        self.assertEqual(t["margin_pct"], round((27719.34 - 22857.26) / 27719.34 * 100, 2))

    def test_unknown_cost_blanks_profit_and_margin(self):
        t = bov._totals_dict(revenue=500.0, cost=0.0, returns=0.0, orders=2, units=4.0, cost_coverage=0.0)
        self.assertEqual((t["profit"], t["margin_pct"], t["revenue"]), (None, None, 500.0))

    def test_zero_units_with_zero_coverage_is_not_unknown(self):
        t = bov._totals_dict(revenue=0.0, cost=0.0, returns=0.0, orders=0, units=0.0, cost_coverage=0.0)
        self.assertEqual((t["profit"], t["margin_pct"]), (0.0, None))

    def test_empty_totals_carry_every_field_at_zero(self):
        self.assertEqual(bov.empty_totals(), {
            "revenue": 0.0, "gross_revenue": 0.0, "cost": 0.0, "profit": 0.0, "shipping_cost": 0.0,
            "shipping_collected": 0.0, "margin_pct": None, "returns": 0.0, "net_revenue": 0.0,
            "orders": 0, "units": 0.0, "cost_coverage": None,
        })


class AddTotalsTests(unittest.TestCase):
    def test_sums_fields_and_weights_coverage_by_units(self):
        a = bov._totals_dict(100.0, 40.0, 5.0, 1, 10.0, cost_coverage=1.0, gross_revenue=110.0, net_revenue=100.0)
        b = bov._totals_dict(200.0, 100.0, 0.0, 2, 30.0, cost_coverage=0.5, shipping=7.0)
        s = bov.add_totals(a, b)
        self.assertEqual(s, {
            "revenue": 300.0, "gross_revenue": 310.0, "cost": 140.0, "profit": 153.0,
            "shipping_cost": 7.0, "shipping_collected": 0.0,
            "margin_pct": round(160 / 300 * 100, 2), "returns": 5.0, "net_revenue": 300.0,
            "orders": 3, "units": 40.0, "cost_coverage": round((10 * 1.0 + 30 * 0.5) / 40, 4),
        })

    def test_unknown_profit_on_either_side_stays_unknown(self):
        known = bov._totals_dict(100.0, 40.0, 0.0, 1, 10.0, cost_coverage=1.0)
        unknown = bov._totals_dict(50.0, 0.0, 0.0, 1, 5.0, cost_coverage=0.0)
        for left, right in ((known, unknown), (unknown, known)):
            s = bov.add_totals(left, right)
            self.assertEqual((s["profit"], s["margin_pct"], s["revenue"]), (None, None, 150.0))

    def test_adding_empty_totals_is_identity(self):
        t = bov._totals_dict(100.0, 40.0, 5.0, 1, 10.0, cost_coverage=1.0, shipping=3.0, shipping_collected=2.0)
        self.assertEqual(bov.add_totals(t, bov.empty_totals()), t)
        self.assertEqual(bov.add_totals(bov.empty_totals(), t), t)


class AddShippingCostTests(unittest.TestCase):
    def test_folds_shipping_into_profit(self):
        t = bov._totals_dict(100.0, 40.0, 0.0, 1, 10.0, cost_coverage=1.0, shipping_collected=8.0)
        bov.add_shipping_cost(t, 12.5)
        self.assertEqual((t["shipping_cost"], t["profit"]), (12.5, 55.5))

    def test_unknown_profit_is_preserved(self):
        t = bov._totals_dict(100.0, 0.0, 0.0, 1, 10.0, cost_coverage=0.0)
        bov.add_shipping_cost(t, 12.5)
        self.assertEqual((t["shipping_cost"], t["profit"]), (12.5, None))

    def test_zero_amount_is_a_no_op(self):
        t = bov._totals_dict(100.0, 40.0, 0.0, 1, 10.0, cost_coverage=1.0)
        before = dict(t)
        bov.add_shipping_cost(t, 0.0)
        self.assertEqual(t, before)


class TotalsChangeTests(unittest.TestCase):
    def test_percent_change_per_field_and_margin_in_points(self):
        cur = bov._totals_dict(200.0, 100.0, 10.0, 4, 20.0, cost_coverage=1.0)
        prev = bov._totals_dict(100.0, 60.0, 5.0, 2, 10.0, cost_coverage=1.0)
        self.assertEqual(bov.totals_change(cur, prev), {
            "revenue": 100.0, "gross_revenue": 100.0, "cost": round(40 / 60 * 100, 2), "profit": 150.0,
            "shipping_cost": None, "shipping_collected": None, "orders": 100.0, "units": 100.0,
            "returns": 100.0, "net_revenue": 100.0, "margin_pct": 10.0,
        })

    def test_unknown_profit_gives_none_not_zero(self):
        cur = bov._totals_dict(200.0, 0.0, 0.0, 4, 20.0, cost_coverage=0.0)
        prev = bov._totals_dict(100.0, 60.0, 0.0, 2, 10.0, cost_coverage=1.0)
        ch = bov.totals_change(cur, prev)
        self.assertEqual((ch["profit"], ch["margin_pct"], ch["revenue"]), (None, None, 100.0))


class ShopifyLineNetRevenueTests(unittest.TestCase):
    def test_pro_rates_by_remaining_units(self):
        self.assertAlmostEqual(bov.shopify_line_net_revenue("30.00", 3, 2), 20.0)

    def test_null_current_quantity_means_ordered_quantity(self):
        self.assertAlmostEqual(bov.shopify_line_net_revenue(30.0, 3, None), 30.0)

    def test_fully_refunded_line_carries_nothing(self):
        self.assertEqual(bov.shopify_line_net_revenue(30.0, 3, 0), 0.0)

    def test_zero_ordered_quantity_returns_the_total_unchanged(self):
        self.assertEqual(bov.shopify_line_net_revenue(12.5, 0, 0), 12.5)


class UnitCostForTests(unittest.TestCase):
    def test_sale_uses_stamped_line_cost_when_present(self):
        self.assertEqual(bov._unit_cost_for("sale", 4.25, 5.0), 4.25)

    def test_sale_falls_back_to_item_cost_for_blank_or_zero_line_cost(self):
        self.assertEqual(bov._unit_cost_for("sale", 0.0, 5.0), 5.0)
        self.assertEqual(bov._unit_cost_for("sale", None, 5.0), 5.0)

    def test_current_prefers_item_cost_and_falls_back_to_line_cost(self):
        self.assertEqual(bov._unit_cost_for("current", 4.25, 5.0), 5.0)
        self.assertEqual(bov._unit_cost_for("current", 4.25, None), 4.25)

    def test_s2s_behaves_like_current_in_sql_twin(self):
        self.assertEqual(bov._unit_cost_for("s2s", 4.25, 5.0), 5.0)
        self.assertEqual(bov._unit_cost_for("s2s", 4.25, None), 4.25)

    def test_nothing_known_is_none(self):
        self.assertIsNone(bov._unit_cost_for("sale", None, None))
        self.assertIsNone(bov._unit_cost_for("current", None, None))


class RatioGuardTests(unittest.TestCase):
    def test_margin_pct(self):
        self.assertEqual(bov.margin_pct(200.0, 150.0), 25.0)
        self.assertIsNone(bov.margin_pct(0.0, 10.0))
        self.assertEqual(bov.margin_pct(100.0, 130.0), -30.0)

    def test_pct_change(self):
        self.assertEqual(bov.pct_change(150.0, 100.0), 50.0)
        self.assertEqual(bov.pct_change(-50.0, -100.0), 50.0)
        self.assertIsNone(bov.pct_change(10.0, 0.0))
        self.assertIsNone(bov.pct_change(None, 10.0))
        self.assertIsNone(bov.pct_change(10.0, None))


class PeriodTests(unittest.TestCase):
    TODAY = date(2026, 9, 6)  # a Sunday

    def test_whole_month_compares_against_the_month_before(self):
        p = bov.resolve_period("2026-08-01", "2026-08-31", None, "America/Chicago", today=self.TODAY)
        self.assertEqual((p.start, p.end, p.prev_start, p.prev_end, p.days),
                         (date(2026, 8, 1), date(2026, 8, 31), date(2026, 7, 1), date(2026, 7, 31), 31))

    def test_two_whole_months_compare_against_the_two_before(self):
        self.assertEqual(bov.previous_period(date(2026, 3, 1), date(2026, 4, 30)),
                         (date(2026, 1, 1), date(2026, 2, 28)))

    def test_partial_range_compares_against_same_length_window(self):
        self.assertEqual(bov.previous_period(date(2026, 8, 10), date(2026, 8, 19)),
                         (date(2026, 7, 31), date(2026, 8, 9)))

    def test_this_week_starts_monday(self):
        p = bov.resolve_period(None, None, "this_week", "UTC", today=self.TODAY)
        self.assertEqual((p.start, p.end, p.prev_start, p.prev_end, p.preset),
                         (date(2026, 8, 31), date(2026, 9, 6), date(2026, 8, 24), date(2026, 8, 30), "this_week"))

    def test_last_week_is_monday_to_sunday(self):
        p = bov.resolve_period(None, None, "last_week", "UTC", today=self.TODAY)
        self.assertEqual((p.start, p.end), (date(2026, 8, 24), date(2026, 8, 30)))

    def test_no_input_means_today(self):
        p = bov.resolve_period(None, None, None, "UTC", today=self.TODAY)
        self.assertEqual((p.start, p.end, p.prev_start, p.prev_end, p.preset),
                         (self.TODAY, self.TODAY, date(2026, 9, 5), date(2026, 9, 5), "today"))

    def test_rejects_ranges_over_400_days(self):
        with self.assertRaises(ValueError):
            bov.resolve_period("2025-01-01", "2026-02-05", None, "UTC", today=self.TODAY)
        p = bov.resolve_period("2025-01-01", "2026-02-04", None, "UTC", today=self.TODAY)
        self.assertEqual(p.days, 400)

    def test_rejects_reversed_or_half_specified_ranges(self):
        with self.assertRaises(ValueError):
            bov.resolve_period("2026-08-31", "2026-08-01", None, "UTC", today=self.TODAY)
        with self.assertRaises(ValueError):
            bov.resolve_period("2026-08-01", None, None, "UTC", today=self.TODAY)
        with self.assertRaises(ValueError):
            bov.resolve_period(None, None, "fortnight", "UTC", today=self.TODAY)


class RollupDailyTests(unittest.TestCase):
    DAILY = {
        date(2026, 8, 30): {"revenue": 10.0, "units": 1},
        date(2026, 8, 31): {"revenue": 20.0, "units": 2},
        date(2026, 9, 1): {"revenue": 40.0},
        date(2026, 9, 9): {"revenue": 80.0, "units": 8},
    }

    def test_week_buckets_are_monday_based_clipped_and_zero_filled(self):
        out = bov.rollup_daily(self.DAILY, date(2026, 8, 30), date(2026, 9, 9), "week", ["revenue", "units"])
        self.assertEqual(out, [
            {"key": "2026-08-24", "start": "2026-08-30", "end": "2026-08-30", "label": "Wk of Aug 24",
             "values": {"revenue": 10.0, "units": 1.0}},
            {"key": "2026-08-31", "start": "2026-08-31", "end": "2026-09-06", "label": "Wk of Aug 31",
             "values": {"revenue": 60.0, "units": 2.0}},
            {"key": "2026-09-07", "start": "2026-09-07", "end": "2026-09-09", "label": "Wk of Sep 7",
             "values": {"revenue": 80.0, "units": 8.0}},
        ])

    def test_month_buckets(self):
        out = bov.rollup_daily(self.DAILY, date(2026, 8, 1), date(2026, 9, 30), "month", ["revenue"])
        self.assertEqual([(b["key"], b["label"], b["values"]["revenue"]) for b in out],
                         [("2026-08-01", "Aug 2026", 30.0), ("2026-09-01", "Sep 2026", 120.0)])

    def test_day_buckets_outside_data_are_zero(self):
        out = bov.rollup_daily(self.DAILY, date(2026, 9, 2), date(2026, 9, 3), "day", ["revenue"])
        self.assertEqual([b["values"]["revenue"] for b in out], [0.0, 0.0])

    def test_invalid_bucket_is_rejected(self):
        with self.assertRaises(ValueError):
            bov.rollup_daily(self.DAILY, date(2026, 9, 1), date(2026, 9, 2), "quarter", ["revenue"])


class NormalizeOrderNumberTests(unittest.TestCase):
    def test_strips_hash_and_whitespace(self):
        self.assertEqual(bov.normalize_order_number(" #1001 "), "1001")
        self.assertEqual(bov.normalize_order_number("1001"), "1001")
        self.assertEqual(bov.normalize_order_number("##7"), "7")

    def test_none_and_blank_become_empty(self):
        self.assertEqual(bov.normalize_order_number(None), "")
        self.assertEqual(bov.normalize_order_number("  "), "")

    def test_non_string_names_are_stringified(self):
        self.assertEqual(bov.normalize_order_number(1001), "1001")


class BindDtTests(unittest.TestCase):
    def test_date_strings_become_datetimes(self):
        self.assertEqual(bov._bind_dt("2026-08-01"), datetime(2026, 8, 1))
        self.assertEqual(bov._bind_dt("2026-08-01 13:45"), datetime(2026, 8, 1, 13, 45))
        self.assertEqual(bov._bind_dt("2026-08-01 13:45:30"), datetime(2026, 8, 1, 13, 45, 30))

    def test_date_objects_become_midnight_datetimes(self):
        self.assertEqual(bov._bind_dt(date(2026, 8, 1)), datetime(2026, 8, 1))
        self.assertEqual(bov._bind_dt(datetime(2026, 8, 1, 6)), datetime(2026, 8, 1, 6))

    def test_unparseable_values_pass_through(self):
        self.assertEqual(bov._bind_dt("08/01/2026"), "08/01/2026")
        self.assertIsNone(bov._bind_dt(None))
        self.assertEqual(bov._bind_dt(42), 42)


if __name__ == "__main__":
    unittest.main()
