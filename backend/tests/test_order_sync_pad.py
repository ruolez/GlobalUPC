"""
Pure tests for the second Shopify fetch: order_sync_helper.order_pad_windows,
match_orders_staged and build_report's handling of padded orders.

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

import order_sync_helper as osync  # noqa: E402
from test_order_sync_match import _order, _invoice, BASKET, OTHER_BASKET  # noqa: E402

DATE_FROM = "2026-09-17"
DATE_TO = "2026-09-17"
TRACKING = "UDS1432537171"


def _full_invoice(**kw):
    inv = _invoice(**kw)
    inv.update({"invoice_date": inv["date"] + "T12:00:00", "has_tracking": bool(inv["tracking_no"])})
    return inv


class OrderPadWindowsTests(unittest.TestCase):
    def test_next_day_run_pads_one_day_forward_and_three_back(self):
        self.assertEqual(osync.order_pad_windows(DATE_FROM, DATE_TO, "2026-09-18"),
                         [("2026-09-14", "2026-09-16"), ("2026-09-18", "2026-09-18")])

    def test_same_day_run_has_no_forward_window(self):
        self.assertEqual(osync.order_pad_windows(DATE_FROM, DATE_TO, DATE_TO),
                         [("2026-09-14", "2026-09-16")])

    def test_old_period_pads_a_full_month_forward(self):
        self.assertEqual(osync.order_pad_windows("2026-08-01", "2026-08-07", "2026-09-18"),
                         [("2026-07-29", "2026-07-31"), ("2026-08-08", "2026-09-07")])

    def test_forward_window_is_clipped_at_today(self):
        self.assertEqual(osync.order_pad_windows("2026-09-01", "2026-09-10", "2026-09-15")[1],
                         ("2026-09-11", "2026-09-15"))


class StagedMatchingTests(unittest.TestCase):
    def test_leftover_invoice_pairs_with_a_padded_order_by_tracking(self):
        invoice = _invoice(date=DATE_FROM, tracking=TRACKING)
        late = _order(order_id="late", date="2026-09-18", tracking=(TRACKING,))
        result = osync.match_orders_staged([], [invoice], [late])
        self.assertEqual([(m["orders"][0]["name"], m["invoices"][0]["invoice_number"], m["method"]) for m in result["matches"]],
                         [("FSDlate", "90001", "tracking")])
        self.assertEqual((result["unmatched_orders"], result["unmatched_invoices"]), ([], []))

    def test_stage_one_pair_is_final_even_when_a_padded_order_fits_better(self):
        invoice = _invoice(date=DATE_FROM, tracking="")
        in_range = _order(order_id="a", date=DATE_FROM, tracking=())
        padded = _order(order_id="b", date="2026-09-18", tracking=())
        result = osync.match_orders_staged([in_range], [invoice], [padded])
        self.assertEqual([m["orders"][0]["name"] for m in result["matches"]], ["FSDa"])
        self.assertEqual([o["name"] for o in result["unmatched_orders"]], ["FSDb"])

    def test_padded_orders_never_take_an_out_of_range_invoice(self):
        invoice = _invoice(date="2026-09-10", tracking=TRACKING)
        invoice["in_range"] = False
        late = _order(order_id="late", date="2026-09-18", tracking=(TRACKING,))
        result = osync.match_orders_staged([], [invoice], [late])
        self.assertEqual(result["matches"], [])

    def test_no_padded_orders_means_no_second_stage(self):
        invoice = _invoice(date=DATE_FROM, tracking=TRACKING)
        result = osync.match_orders_staged([], [invoice], [])
        self.assertEqual((result["matches"], len(result["unmatched_invoices"])), ([], 1))


class PaddedReportTests(unittest.TestCase):
    def test_padded_order_appears_only_through_its_in_range_invoice(self):
        invoice = _full_invoice(date=DATE_FROM, tracking=TRACKING)
        late = _order(order_id="late", date="2026-09-18", tracking=(TRACKING,))
        stray = _order(order_id="stray", date="2026-09-20", tracking=("1Z9",), barcodes=OTHER_BASKET)
        report = osync.build_report([], [invoice], DATE_FROM, DATE_TO, padded_orders=[late, stray])
        self.assertEqual([(r["status"], r.get("sh_name"), r.get("bo_invoice_number")) for r in report["rows"]],
                         [("matched_ok", "FSDlate", "90001")])
        s = report["summary"]
        self.assertEqual((s["shopify_total"], s["shopify_unmatched"], s["backoffice_unmatched"], s["matched_ok"]), (0, 0, 0, 1))

    def test_in_range_orders_still_count_and_report_when_unmatched(self):
        lonely = _order(order_id="x", date=DATE_FROM, tracking=("1Z1",), barcodes=BASKET)
        report = osync.build_report([lonely], [], DATE_FROM, DATE_TO, padded_orders=[])
        self.assertEqual(([r["status"] for r in report["rows"]], report["summary"]["shopify_total"]), (["shopify_unmatched"], 1))


if __name__ == "__main__":
    unittest.main()
