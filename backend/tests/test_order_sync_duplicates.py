"""
Pure tests for order_sync_helper.plan_duplicate_cancels (no database, no
network). The pass cancels real Shopify orders, so the invariants asserted
here — one survivor per group, targets and survivors disjoint, no identity
fallback — are the safety net, not decoration.

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

import order_sync_helper as osync  # noqa: E402

CUSTOMER = "gid://shopify/Customer/900"
OTHER_CUSTOMER = "gid://shopify/Customer/901"
TOTAL = 1000.0
DATE = "2026-09-10"


def _gid(n):
    return f"gid://shopify/Order/{n}"


def _order(n, customer=CUSTOMER, total=TOTAL, gross=None, date=DATE, tracking=(),
           cancelled=False, net_payment=0.0, refunded=0.0, created_at=None):
    return {
        "id": _gid(n),
        "name": f"FSD{n}",
        "created_at": created_at or f"{date}T12:00:00Z",
        "local_date": date,
        "customer_gid": customer,
        "total": total,
        "gross_total": TOTAL if gross is None and total == TOTAL else (gross if gross is not None else total),
        "refunded": refunded,
        "net_payment": net_payment,
        "financial_status": "PAID" if net_payment else "PENDING",
        "fulfillment_status": "FULFILLED",
        "cancelled": cancelled,
        "tracking_numbers": list(tracking),
    }


def _plan(targets, pool, invoiced=(), protected=()):
    return osync.plan_duplicate_cancels([t["id"] for t in targets], pool,
                                        set(invoiced), set(protected))


def _by_id(plan):
    return {r["sh_order_id"]: r for r in plan["rows"]}


class DupTotalsWithinTests(unittest.TestCase):
    def test_identical_totals_match(self):
        self.assertTrue(osync.dup_totals_within(1000.0, 1000.0))

    def test_just_inside_tolerance_matches(self):
        # 20% of the LARGER total, so 1000 tolerates down to 800.
        self.assertTrue(osync.dup_totals_within(1000.0, 800.0))

    def test_just_outside_tolerance_does_not_match(self):
        self.assertFalse(osync.dup_totals_within(1000.0, 799.0))

    def test_tolerance_is_symmetric(self):
        self.assertEqual(osync.dup_totals_within(1000.0, 800.0),
                         osync.dup_totals_within(800.0, 1000.0))

    def test_zero_totals_do_not_crash(self):
        self.assertTrue(osync.dup_totals_within(0.0, 0.0))
        self.assertFalse(osync.dup_totals_within(0.0, 10.0))


class DupWindowTests(unittest.TestCase):
    def test_same_day_pair_is_proposed(self):
        a = _order(1, tracking=["1Z999"])
        b = _order(2)
        row = _by_id(_plan([b], [a, b]))[b["id"]]
        self.assertEqual((row["status"], row["twin"]["sh_order_id"]), ("proposed", a["id"]))

    def test_eighteen_days_apart_is_proposed(self):
        a = _order(1, date="2026-09-01", tracking=["1Z999"])
        b = _order(2, date="2026-09-19")
        self.assertEqual(_by_id(_plan([b], [a, b]))[b["id"]]["status"], "proposed")

    def test_nineteen_days_apart_is_not_a_duplicate(self):
        a = _order(1, date="2026-09-01", tracking=["1Z999"])
        b = _order(2, date="2026-09-20")
        row = _by_id(_plan([b], [a, b]))[b["id"]]
        self.assertEqual((row["status"], row["twin"]), ("no_twin", None))

    def test_totals_outside_tolerance_are_not_duplicates(self):
        a = _order(1, total=1000.0, gross=1000.0, tracking=["1Z999"])
        b = _order(2, total=700.0, gross=700.0)
        self.assertEqual(_by_id(_plan([b], [a, b]))[b["id"]]["status"], "no_twin")

    def test_gross_totals_must_agree_too(self):
        # A partial refund can pull `total` into the window on its own; the
        # pre-refund figures are still 40% apart, so this is not one sale.
        a = _order(1, total=1000.0, gross=1000.0, tracking=["1Z999"])
        b = _order(2, total=950.0, gross=1600.0, refunded=650.0)
        self.assertEqual(_by_id(_plan([b], [a, b]))[b["id"]]["status"], "no_twin")

    def test_different_customer_is_never_a_twin(self):
        a = _order(1, customer=OTHER_CUSTOMER, tracking=["1Z999"])
        b = _order(2)
        self.assertEqual(_by_id(_plan([b], [a, b]))[b["id"]]["status"], "no_twin")


class DupRankingTests(unittest.TestCase):
    def test_invoiced_candidate_outranks_a_closer_total(self):
        invoiced = _order(1, total=900.0, gross=900.0)
        closer = _order(2, total=1000.0, gross=1000.0)
        target = _order(3, total=1000.0, gross=1000.0)
        row = _by_id(_plan([target], [invoiced, closer, target], invoiced=[invoiced["id"]]))[target["id"]]
        self.assertEqual(row["twin"]["sh_order_id"], invoiced["id"])

    def test_tracked_candidate_outranks_an_untracked_closer_total(self):
        tracked = _order(1, total=900.0, gross=900.0, tracking=["1Z999"])
        closer = _order(2, total=1000.0, gross=1000.0)
        target = _order(3, total=1000.0, gross=1000.0)
        row = _by_id(_plan([target], [tracked, closer, target]))[target["id"]]
        self.assertEqual(row["twin"]["sh_order_id"], tracked["id"])

    def test_route_code_does_not_count_as_tracking(self):
        # "2" is the driver's route, shared by dozens of orders.
        route_only = _order(1, tracking=["2"])
        target = _order(2)
        row = _by_id(_plan([target], [route_only, target]))[target["id"]]
        self.assertFalse(row["twin"]["has_tracking"])

    def test_alternatives_list_the_runners_up(self):
        best = _order(1, tracking=["1Z999"])
        other = _order(2, total=950.0, gross=950.0)
        target = _order(3)
        row = _by_id(_plan([target], [best, other, target]))[target["id"]]
        self.assertEqual([a["sh_order_id"] for a in row["alternatives"]], [other["id"]])


class DupClusterTests(unittest.TestCase):
    def test_two_mutual_duplicates_cancel_exactly_one(self):
        a = _order(1, created_at="2026-09-10T09:00:00Z")
        b = _order(2, created_at="2026-09-10T11:00:00Z")
        rows = _plan([a, b], [a, b])["rows"]
        statuses = {r["sh_order_id"]: r["status"] for r in rows}
        self.assertEqual(statuses, {a["id"]: "no_twin", b["id"]: "ambiguous"})

    def test_survivor_is_never_also_a_cancel_target(self):
        a = _order(1, created_at="2026-09-10T09:00:00Z")
        b = _order(2, created_at="2026-09-10T11:00:00Z")
        c = _order(3, created_at="2026-09-10T13:00:00Z")
        rows = _plan([a, b, c], [a, b, c])["rows"]
        cancelling = {r["sh_order_id"] for r in rows if r["status"] in ("proposed", "ambiguous")}
        surviving = {r["twin"]["sh_order_id"] for r in rows if r["twin"]}
        self.assertEqual(cancelling & surviving, set())

    def test_triplicate_keeps_one_and_points_both_at_it(self):
        keeper = _order(1, tracking=["1Z999"])
        b = _order(2)
        c = _order(3)
        rows = _by_id(_plan([b, c], [keeper, b, c]))
        self.assertEqual([rows[b["id"]]["twin"]["sh_order_id"], rows[c["id"]]["twin"]["sh_order_id"]],
                         [keeper["id"], keeper["id"]])

    def test_the_day_window_is_not_widened_by_chaining(self):
        # A~B and B~C are each inside the window, A~C is not. C must pair with
        # B, never with A — a repeat customer would otherwise chain a whole
        # quarter of orders into one group.
        a = _order(1, date="2026-09-01")
        b = _order(2, date="2026-09-18")
        c = _order(3, date="2026-09-30")
        rows = _by_id(_plan([a, b, c], [a, b, c]))
        self.assertEqual(rows[c["id"]]["twin"]["sh_order_id"], b["id"])
        self.assertEqual(rows[a["id"]]["status"], "no_twin")

    def test_a_twin_that_is_itself_being_cancelled_is_flagged(self):
        a = _order(1, date="2026-09-01")
        b = _order(2, date="2026-09-18")
        c = _order(3, date="2026-09-30")
        row = _by_id(_plan([a, b, c], [a, b, c]))[c["id"]]
        self.assertIn("the order it duplicates is also in this list", row["reason"])

    def test_a_lower_ranked_third_order_does_not_cloud_the_pairing(self):
        # `c` ranks below the target, so it is a fellow duplicate rather than
        # a candidate to survive — only `keeper` could be the original.
        keeper = _order(1, tracking=["1Z999"])
        b = _order(2)
        c = _order(3)
        row = _by_id(_plan([b], [keeper, b, c]))[b["id"]]
        self.assertEqual((row["status"], row["cluster_size"]), ("proposed", 2))

    def test_two_possible_originals_are_ambiguous(self):
        keeper = _order(1, tracking=["1Z999"])
        other = _order(2, total=950.0, gross=950.0)
        target = _order(3)
        row = _by_id(_plan([target], [keeper, other, target]))[target["id"]]
        self.assertEqual(row["status"], "ambiguous")
        self.assertIn("2 orders from this customer qualify", row["reason"])

    def test_the_closest_eligible_order_wins_not_the_oldest(self):
        # Both are reconciled to an invoice, so rank cannot separate them;
        # reaching past the next-day twin to an older order is the bug this
        # guards against.
        old_invoiced = _order(1, total=1150.0, gross=1150.0, date="2026-08-26")
        next_day = _order(2, total=1020.0, gross=1020.0, date="2026-09-11")
        target = _order(3, total=1000.0, gross=1000.0, date="2026-09-10")
        row = _by_id(_plan([target], [old_invoiced, next_day, target],
                           invoiced=[old_invoiced["id"], next_day["id"]]))[target["id"]]
        self.assertEqual(row["twin"]["sh_order_id"], next_day["id"])

    def test_untracked_uninvoiced_pair_is_ambiguous_not_proposed(self):
        a = _order(1, created_at="2026-09-10T09:00:00Z")
        b = _order(2, created_at="2026-09-10T11:00:00Z")
        row = _by_id(_plan([b], [a, b]))[b["id"]]
        self.assertEqual(row["status"], "ambiguous")
        self.assertIn("neither order has an invoice or tracking", row["reason"])


class DupEligibilityTests(unittest.TestCase):
    def test_order_without_a_customer_is_skipped_with_no_fallback(self):
        a = _order(1, tracking=["1Z999"])
        b = _order(2, customer=None)
        row = _by_id(_plan([b], [a, b]))[b["id"]]
        self.assertEqual((row["status"], row["reason"]),
                         ("no_twin", "Order has no Shopify customer"))

    def test_an_order_is_never_its_own_twin(self):
        b = _order(2)
        self.assertEqual(_by_id(_plan([b], [b]))[b["id"]]["status"], "no_twin")

    def test_protected_survivor_is_never_a_target(self):
        a = _order(1, tracking=["1Z999"])
        b = _order(2)
        row = _by_id(_plan([b], [a, b], protected=[b["id"]]))[b["id"]]
        self.assertEqual(row["status"], "blocked")

    def test_missing_from_the_pool_is_blocked(self):
        a = _order(1, tracking=["1Z999"])
        b = _order(2)
        row = _by_id(_plan([b], [a]))[b["id"]]
        self.assertEqual(row["status"], "blocked")

    def test_already_cancelled_target_is_blocked(self):
        a = _order(1, tracking=["1Z999"])
        b = _order(2, cancelled=True)
        self.assertEqual(_by_id(_plan([b], [a, b]))[b["id"]]["status"], "blocked")


class DupFlagTests(unittest.TestCase):
    def test_small_total_is_flagged_and_downgraded_not_dropped(self):
        a = _order(1, total=20.0, gross=20.0, tracking=["1Z999"])
        b = _order(2, total=20.0, gross=20.0)
        row = _by_id(_plan([b], [a, b]))[b["id"]]
        self.assertEqual((row["status"], row["flags"]), ("ambiguous", ["low_total"]))

    def test_paid_order_is_flagged_but_still_proposed(self):
        a = _order(1, tracking=["1Z999"])
        b = _order(2, net_payment=TOTAL)
        row = _by_id(_plan([b], [a, b]))[b["id"]]
        self.assertEqual((row["status"], row["flags"]), ("proposed", ["paid"]))


class DupReportingTests(unittest.TestCase):
    def test_deltas_describe_the_pair(self):
        a = _order(1, total=1000.0, gross=1000.0, date="2026-09-08", tracking=["1Z999"])
        b = _order(2, total=900.0, gross=900.0, date="2026-09-10")
        row = _by_id(_plan([b], [a, b]))[b["id"]]
        self.assertEqual((row["total_delta"], row["total_delta_pct"], row["date_delta_days"],
                          row["cluster_size"]),
                         (-100.0, 10.0, 2, 2))

    def test_summary_counts_every_target_once(self):
        a = _order(1, tracking=["1Z999"])
        b = _order(2)
        c = _order(3, customer=OTHER_CUSTOMER)
        plan = _plan([b, c], [a, b, c])
        self.assertEqual(plan["summary"],
                         {"targets": 2, "proposed": 1, "ambiguous": 0, "no_twin": 1, "blocked": 0})

    def test_planning_twice_gives_the_same_answer(self):
        a = _order(1, tracking=["1Z999"])
        b = _order(2)
        self.assertEqual(_plan([b], [a, b]), _plan([b], [a, b]))


class DupStaffNoteTests(unittest.TestCase):
    def test_note_names_the_surviving_order(self):
        import order_sync_fix_helper as ofix
        note = ofix.dup_staff_note({"sh_order_id": _gid(1), "sh_name": "FSD12290",
                                    "sh_date": "2026-09-05", "sh_total": 1725.19})
        self.assertEqual(note, "Duplicate of FSD12290 (2026-09-05, $1,725.19) — cancelled by Order Sync")


if __name__ == "__main__":
    unittest.main()
