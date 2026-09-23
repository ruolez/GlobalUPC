"""
Pure tests for the Order Sync "Online Store" cancel pass: channel naming,
the target rule (Online Store AND not UNFULFILLED AND not cancelled AND
placed in range) and the informational web-hook copy lookup. The pass
cancels real Shopify orders, so the target rule is asserted exhaustively.

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

import asyncio  # noqa: E402

import order_sync_fix_helper as ofix  # noqa: E402
import order_sync_helper as osync  # noqa: E402

ONLINE = "Online Store"
WEBHOOK = "web hook"
CUSTOMER = "gid://shopify/Customer/900"
OTHER_CUSTOMER = "gid://shopify/Customer/901"
TOTAL = 500.0
DATE = "2026-09-10"
DATE_FROM = "2026-09-01"
DATE_TO = "2026-09-30"

# Every displayFulfillmentStatus the Admin API can return.
FULFILLMENT_STATUSES = [
    "FULFILLED", "PARTIALLY_FULFILLED", "UNFULFILLED", "IN_PROGRESS", "ON_HOLD",
    "OPEN", "PENDING_FULFILLMENT", "RESTOCKED", "SCHEDULED", "REQUEST_DECLINED",
]


def _gid(n):
    return f"gid://shopify/Order/{n}"


def _order(n, channel=ONLINE, status="FULFILLED", customer=CUSTOMER, total=TOTAL,
           date=DATE, cancelled=False, net_payment=0.0, tracking=()):
    return {
        "id": _gid(n), "name": f"#{n}", "created_at": f"{date}T12:00:00Z",
        "local_date": date, "customer_gid": customer, "channel": channel,
        "total": total, "gross_total": total, "refunded": 0.0,
        "net_payment": net_payment, "financial_status": "PAID" if net_payment else "PENDING",
        "fulfillment_status": status, "cancelled": cancelled,
        "tracking_numbers": list(tracking),
    }


def _plan(pool, busy=()):
    return osync.plan_channel_cancels(pool, DATE_FROM, DATE_TO, set(busy))


def _ids(plan):
    return [r["sh_order_id"] for r in plan["rows"]]


class OrderChannelTests(unittest.TestCase):
    def test_app_name_wins_over_source_name(self):
        self.assertEqual(osync.order_channel(WEBHOOK, "web"), WEBHOOK)

    def test_web_source_is_online_store(self):
        self.assertEqual(osync.order_channel(None, "web"), ONLINE)

    def test_unknown_source_name_passes_through(self):
        self.assertEqual(osync.order_channel("", "1234567"), "1234567")

    def test_nothing_known_is_none(self):
        self.assertIsNone(osync.order_channel(None, None))

    def test_is_online_store_ignores_case_and_space(self):
        self.assertEqual([osync.is_online_store(c) for c in (" online store ", WEBHOOK, None)],
                         [True, False, False])


class TargetRuleTests(unittest.TestCase):
    def test_every_status_but_unfulfilled_is_a_target(self):
        pool = [_order(i, status=s) for i, s in enumerate(FULFILLMENT_STATUSES, start=1)]
        expected = [_gid(i) for i, s in enumerate(FULFILLMENT_STATUSES, start=1) if s != "UNFULFILLED"]
        self.assertEqual(sorted(_ids(_plan(pool))), sorted(expected))

    def test_other_channels_are_never_targets(self):
        pool = [_order(1, channel=WEBHOOK), _order(2, channel=None), _order(3, channel="Draft Orders")]
        self.assertEqual(_ids(_plan(pool)), [])

    def test_cancelled_orders_are_not_targets(self):
        self.assertEqual(_ids(_plan([_order(1, cancelled=True)])), [])

    def test_orders_outside_the_range_are_not_targets(self):
        pool = [_order(1, date="2026-08-31"), _order(2, date=DATE_FROM), _order(3, date=DATE_TO),
                _order(4, date="2026-10-01")]
        self.assertEqual(sorted(_ids(_plan(pool))), [_gid(2), _gid(3)])

    def test_busy_order_is_blocked(self):
        plan = _plan([_order(1), _order(2)], busy=[_gid(1)])
        self.assertEqual([(r["sh_order_id"], r["status"]) for r in plan["rows"]],
                         [(_gid(1), "blocked"), (_gid(2), "proposed")])
        self.assertEqual(plan["summary"], {"targets": 2, "proposed": 1, "blocked": 1, "with_copy": 0})

    def test_fulfilled_paid_order_carries_flags(self):
        row = _plan([_order(1, net_payment=TOTAL, tracking=("1Z999",))])["rows"][0]
        self.assertEqual(row["flags"], ["paid", "has_tracking", "fulfilled"])


class WebhookCopyTests(unittest.TestCase):
    def test_same_customer_webhook_order_is_the_copy(self):
        row = _plan([_order(1), _order(2, channel=WEBHOOK, date="2026-09-11")])["rows"][0]
        self.assertEqual((row["copy"]["sh_order_id"], row["copy"]["channel"], row["date_delta_days"]),
                         (_gid(2), WEBHOOK, 1))

    def test_closest_total_wins(self):
        pool = [_order(1), _order(2, channel=WEBHOOK, total=TOTAL * 0.9),
                _order(3, channel=WEBHOOK, total=TOTAL * 0.99)]
        self.assertEqual(_plan(pool)["rows"][0]["copy"]["sh_order_id"], _gid(3))

    def test_no_copy_across_customers_totals_or_days(self):
        far = osync.DUP_MAX_DAYS_APART + 1
        pool = [
            _order(1),
            _order(2, channel=WEBHOOK, customer=OTHER_CUSTOMER),
            _order(3, channel=WEBHOOK, total=TOTAL * (1 - osync.DUP_TOTAL_TOL_PCT) - 1),
            _order(4, channel=WEBHOOK, date=f"2026-09-{10 + far}"),
        ]
        row = _plan(pool)["rows"][0]
        self.assertEqual((row["copy"], row["status"]), (None, "proposed"))

    def test_another_online_store_order_is_never_the_copy(self):
        rows = _plan([_order(1), _order(2)])["rows"]
        self.assertEqual([r["copy"] for r in rows], [None, None])


FULFILLMENT = "gid://shopify/Fulfillment/7"
REFUSAL = "Cannot cancel an order with fulfillments"


def _state(cancelled=False, channel=ONLINE, status="FULFILLED"):
    return {"id": _gid(1), "name": "#1", "cancelled": cancelled, "cancelled_at": None,
            "channel": channel, "fulfillment_status": status,
            "fulfillments": [{"id": FULFILLMENT, "status": "SUCCESS"},
                             {"id": "gid://shopify/Fulfillment/8", "status": "CANCELLED"}],
            "tracking_numbers": []}


class ApplyChannelCancelTests(unittest.TestCase):
    """The executor's decisions with every Shopify call replaced by a fake
    that records what was called."""

    def setUp(self):
        self.calls = []
        self.refuse_first_cancel = False
        self.cancelled_after = True
        self.state = _state()
        saved = {n: getattr(ofix, n) for n in
                 ("fetch_cancel_state", "cancel_order", "cancel_fulfillment", "wait_for_cancel")}
        self.addCleanup(lambda: [setattr(ofix, n, f) for n, f in saved.items()])

        async def fetch_cancel_state(ctx, gid):
            return self.state

        async def cancel_order(ctx, gid, note):
            self.calls.append(("cancel", note))
            if self.refuse_first_cancel and self.calls.count(("cancel", note)) == 1:
                raise ofix.FixStepError("cancel", REFUSAL)
            return "gid://shopify/Job/1"

        async def cancel_fulfillment(ctx, gid):
            self.calls.append(("fulfillment_cancel", gid))

        async def wait_for_cancel(ctx, gid, job):
            return {"cancelled": self.cancelled_after, "cancelled_at": "2026-09-23T00:00:00Z",
                    "state": self.state}

        ofix.fetch_cancel_state = fetch_cancel_state
        ofix.cancel_order = cancel_order
        ofix.cancel_fulfillment = cancel_fulfillment
        ofix.wait_for_cancel = wait_for_cancel

    def _run(self):
        return asyncio.run(ofix.apply_channel_cancel(None, {"sh_order_id": _gid(1), "sh_name": "#1"}))

    def test_plain_cancel_touches_no_fulfillment(self):
        result = self._run()
        self.assertEqual((result["status"], result["fulfillments_cancelled"], [c[0] for c in self.calls]),
                         ("cancelled", 0, ["cancel"]))

    def test_fulfillment_refusal_cancels_successful_fulfillments_then_retries(self):
        self.refuse_first_cancel = True
        result = self._run()
        self.assertEqual((result["status"], result["fulfillments_cancelled"], [c[0] for c in self.calls]),
                         ("cancelled", 1, ["cancel", "fulfillment_cancel", "cancel"]))

    def test_other_refusals_fail_without_touching_fulfillments(self):
        async def cancel_order(ctx, gid, note):
            raise ofix.FixStepError("cancel", "Order has pending payment authorizations")
        ofix.cancel_order = cancel_order
        result = self._run()
        self.assertEqual((result["status"], self.calls), ("failed", []))

    def test_job_that_leaves_order_open_triggers_the_fallback_once(self):
        self.cancelled_after = False
        result = self._run()
        self.assertEqual((result["status"], [c[0] for c in self.calls]),
                         ("failed", ["cancel", "fulfillment_cancel", "cancel"]))

    def test_order_no_longer_online_store_is_skipped(self):
        self.state = _state(channel=WEBHOOK)
        self.assertEqual((self._run()["status"], self.calls), ("skipped", []))

    def test_order_now_unfulfilled_is_skipped(self):
        self.state = _state(status="UNFULFILLED")
        self.assertEqual((self._run()["status"], self.calls), ("skipped", []))

    def test_already_cancelled_is_noop(self):
        self.state = _state(cancelled=True)
        self.assertEqual((self._run()["status"], self.calls), ("noop", []))

    def test_staff_note_names_the_copy_and_says_no_email(self):
        note = ofix.channel_staff_note({"sh_name": "#2", "channel": WEBHOOK})
        self.assertEqual(note, "Online Store duplicate of order #2 (web hook) — "
                               "cancelled by Order Sync (no refund, customer not notified)")


if __name__ == "__main__":
    unittest.main()
