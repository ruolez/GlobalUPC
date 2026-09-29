"""
Pure tests for the Order Sync automation rules (order_sync_auto) and the
per-step fix filter (order_sync_helper.filter_fix_plan).

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import sys
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

import order_sync_auto as auto  # noqa: E402
import order_sync_helper as osync  # noqa: E402

TZ = "America/Chicago"
RUN_TIME = "06:00"
MONDAY = date(2026, 9, 28)        # a Monday
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def _at(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=ZoneInfo(TZ))


def _cfg(**over):
    cfg = {"enabled": True, "run_time": RUN_TIME, "days": ALL_DAYS, "timezone": TZ,
           "effective_from": _at(MONDAY - timedelta(days=30), 0)}
    cfg.update(over)
    return cfg


class DueSlotTests(unittest.TestCase):
    def test_due_at_run_time(self):
        self.assertEqual(auto.due_slot(_at(MONDAY, 6), _cfg(), set()), MONDAY)

    def test_not_due_before_run_time(self):
        self.assertIsNone(auto.due_slot(_at(MONDAY, 5, 59), _cfg(), set()))

    def test_not_due_when_disabled(self):
        self.assertIsNone(auto.due_slot(_at(MONDAY, 7), _cfg(enabled=False), set()))

    def test_not_due_on_unselected_weekday(self):
        self.assertIsNone(auto.due_slot(_at(MONDAY, 7), _cfg(days=[1, 2, 3, 4]), set()))

    def test_not_due_when_already_recorded(self):
        self.assertIsNone(auto.due_slot(_at(MONDAY, 7), _cfg(), {MONDAY}))

    def test_enabling_after_todays_slot_waits_for_tomorrow(self):
        cfg = _cfg(effective_from=_at(MONDAY, 15))
        self.assertEqual((auto.due_slot(_at(MONDAY, 16), cfg, set()),
                          auto.due_slot(_at(MONDAY + timedelta(days=1), 6), cfg, set())),
                         (None, MONDAY + timedelta(days=1)))

    def test_same_day_catch_up_is_due_and_labelled(self):
        now = _at(MONDAY, 14)
        self.assertEqual((auto.due_slot(now, _cfg(), set()), auto.slot_trigger(now, MONDAY, _cfg())),
                         (MONDAY, "catch_up"))

    def test_on_time_run_is_labelled_scheduled(self):
        now = _at(MONDAY, 6, 1)
        self.assertEqual(auto.slot_trigger(now, MONDAY, _cfg()), "scheduled")

    def test_due_uses_config_timezone_not_utc(self):
        # 11:30 UTC = 06:30 CDT: due in Chicago.
        now_utc = datetime(2026, 9, 28, 11, 30, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(auto.due_slot(now_utc, _cfg(), set()), MONDAY)


class MissedSlotTests(unittest.TestCase):
    def test_lists_unrecorded_days_since_effective(self):
        cfg = _cfg(effective_from=_at(MONDAY - timedelta(days=3), 0))
        recorded = {MONDAY - timedelta(days=2)}
        self.assertEqual(auto.missed_slots(_at(MONDAY, 3), cfg, recorded),
                         [MONDAY - timedelta(days=3), MONDAY - timedelta(days=1)])

    def test_skips_unselected_weekdays(self):
        cfg = _cfg(days=[0], effective_from=_at(MONDAY - timedelta(days=10), 0))
        self.assertEqual(auto.missed_slots(_at(MONDAY, 3), cfg, set()), [MONDAY - timedelta(days=7)])

    def test_nothing_when_disabled(self):
        self.assertEqual(auto.missed_slots(_at(MONDAY, 3), _cfg(enabled=False), set()), [])


class NextRunTests(unittest.TestCase):
    def test_later_today(self):
        self.assertEqual(auto.next_run_at(_at(MONDAY, 5), _cfg(), set()), _at(MONDAY, 6))

    def test_tomorrow_once_today_ran(self):
        self.assertEqual(auto.next_run_at(_at(MONDAY, 7), _cfg(), {MONDAY}),
                         _at(MONDAY + timedelta(days=1), 6))

    def test_skips_to_next_selected_weekday(self):
        self.assertEqual(auto.next_run_at(_at(MONDAY, 7), _cfg(days=[3]), set()),
                         _at(MONDAY + timedelta(days=3), 6))

    def test_none_without_days(self):
        self.assertIsNone(auto.next_run_at(_at(MONDAY, 7), _cfg(days=[]), set()))


class ParseTests(unittest.TestCase):
    def test_parse_run_time(self):
        self.assertEqual(auto.parse_run_time("07:45"), (7, 45))

    def test_parse_run_time_rejects_garbage(self):
        for bad in ("7", "25:00", "07:60", "ab:cd", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    auto.parse_run_time(bad)

    def test_normalize_steps_keeps_only_known_keys(self):
        steps = auto.normalize_steps({"fix_lines": 1, "bogus": True})
        self.assertEqual(steps, {k: k == "fix_lines" for k in auto.STEP_KEYS})


def _row(**over):
    row = {"status": "matched_diffs", "sh_order_id": "gid://shopify/Order/1", "sh_name": "#1",
           "bo_invoice_id": 10, "bo_invoice_number": "INV10", "combined": False, "ambiguous": False,
           "issue_kinds": ["qty"], "sh_no_tracking": False, "bo_tracking": None, "sh_outstanding": 0,
           "match_method": "tracking"}
    row.update(over)
    return row


class SelectionTests(unittest.TestCase):
    def test_line_issue_row_is_a_target(self):
        targets, review = auto.select_fix_targets([_row()])
        self.assertEqual((targets, review), ([{
            "sh_order_id": "gid://shopify/Order/1", "bo_invoice_id": 10, "bo_invoice_number": "INV10",
            "match_method": "tracking", "ambiguous": False}], []))

    def test_ambiguous_row_goes_to_review(self):
        targets, review = auto.select_fix_targets([_row(ambiguous=True)])
        self.assertEqual((targets, [r["category"] for r in review]), ([], ["ambiguous_match"]))

    def test_combined_row_with_line_issue_goes_to_review(self):
        targets, review = auto.select_fix_targets([_row(combined=True)])
        self.assertEqual((targets, [r["category"] for r in review]), ([], ["combined"]))

    def test_total_only_difference_is_not_touched(self):
        self.assertEqual(auto.select_fix_targets([_row(issue_kinds=["total"])]), ([], []))

    def test_tracking_and_unpaid_rows_are_targets(self):
        rows = [_row(issue_kinds=[], status="matched_ok", sh_no_tracking=True, bo_tracking="1Z"),
                _row(issue_kinds=[], status="matched_ok", sh_outstanding=5.0, sh_order_id="gid://shopify/Order/2")]
        targets, _review = auto.select_fix_targets(rows)
        self.assertEqual([t["sh_order_id"] for t in targets],
                         ["gid://shopify/Order/1", "gid://shopify/Order/2"])

    def test_dup_targets_are_untracked_shopify_only_rows(self):
        rows = [_row(status="shopify_unmatched", sh_no_tracking=True),
                _row(status="shopify_unmatched", sh_no_tracking=False, sh_order_id="gid://shopify/Order/2"),
                _row(status="matched_ok", sh_no_tracking=True, sh_order_id="gid://shopify/Order/3")]
        self.assertEqual(auto.select_dup_targets(rows), ["gid://shopify/Order/1"])

    def test_invoice_by_order_maps_every_order_of_matched_rows(self):
        rows = [_row(sh_orders=[{"id": "A"}, {"id": "B"}]),
                _row(status="shopify_unmatched", sh_orders=[{"id": "C"}])]
        self.assertEqual(auto.invoice_by_order(rows), {"A": "INV10", "B": "INV10"})


class ReportTests(unittest.TestCase):
    def test_summary_delta(self):
        before = {k: 5 for k in auto.SUMMARY_KEYS + ("fixable", "missing_tracking_shopify_only")}
        after = {**before, "matched_diffs": 2, "matched_ok": 8}
        delta = auto.summary_delta(before, after)
        self.assertEqual({k: v for k, v in delta.items() if v}, {"matched_diffs": -3, "matched_ok": 3})

    def test_final_status(self):
        self.assertEqual([auto.final_status({}, False), auto.final_status({"fix_failed": 1}, False),
                          auto.final_status({}, True)], ["succeeded", "partial", "stopped"])


def _plan(actions):
    return {"actions": actions, "unsupported": [], "notes": [], "summary": {}, "noop": not actions}


REFUND = {"kind": "refund", "reason": "reduce", "key": "0001", "qty": 1, "unit_price": 2.0}
ADD = {"kind": "add", "reason": "add", "key": "0002", "qty": 2, "unit_price": 3.0}
SHIP_ADD = {"kind": "add", "reason": "add", "key": osync.SHIPPING_KEY, "qty": 1, "unit_price": 9.0}
SHIP_LINE = {"kind": "shipping_line", "reason": "shipping"}
TRACKING = {"kind": "tracking", "reason": "tracking", "numbers": ["1Z"], "fulfillment_ids": ["f"]}
MARK_PAID = {"kind": "mark_paid", "reason": "mark_paid", "amount": 4.5}
STORE_PRICE = {"kind": "variant_price", "reason": "price", "key": "0002"}
CREATE = {"kind": "create_product", "reason": "create", "key": "0002"}
ALL_ACTIONS = [CREATE, REFUND, ADD, SHIP_ADD, SHIP_LINE, TRACKING, MARK_PAID, STORE_PRICE]


class FilterFixPlanTests(unittest.TestCase):
    def test_none_keeps_everything(self):
        out = osync.filter_fix_plan(_plan(ALL_ACTIONS), None)
        self.assertEqual((out["actions"], out["skipped_actions"]), (ALL_ACTIONS, []))

    def test_each_switch_keeps_only_its_actions(self):
        expected = {
            "fix_lines": ["refund", "add"],
            "fix_shipping": ["add", "shipping_line"],
            "push_tracking": ["tracking"],
            "mark_paid": ["mark_paid"],
            "store_price": ["variant_price"],
            "create_products": [],          # useless without fix_lines
        }
        for step, kinds in expected.items():
            with self.subTest(step=step):
                out = osync.filter_fix_plan(_plan(ALL_ACTIONS), {step: True})
                self.assertEqual([a["kind"] for a in out["actions"]], kinds)

    def test_create_products_with_fix_lines(self):
        out = osync.filter_fix_plan(_plan(ALL_ACTIONS), {"fix_lines": True, "create_products": True})
        self.assertEqual([a["kind"] for a in out["actions"]], ["create_product", "refund", "add"])

    def test_skipped_actions_name_their_switch_and_noop_is_recomputed(self):
        out = osync.filter_fix_plan(_plan([TRACKING, MARK_PAID]), {"fix_lines": True})
        self.assertEqual((out["noop"], [a["step"] for a in out["skipped_actions"]], out["summary"]["mark_paid"]),
                         (True, ["push_tracking", "mark_paid"], 0.0))


if __name__ == "__main__":
    unittest.main()
