"""
Pure tests for order_sync_helper.collectible_balance (no database, no network).

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

# FSD12435 after its second fix (live figures): Shopify's gross outstanding was
# 15.50 while the current total sat 109.50 below the payments received.
CURRENT_TOTAL = 1986.0
NET_PAYMENT = 2095.5
# FSD12480 after its re-run: 12.00 really owed, Shopify allowed the payment.
OWED_CURRENT = 7971.5
OWED_NET = 7959.5


class CollectibleBalanceTests(unittest.TestCase):
    def test_nothing_to_collect_when_shopify_says_the_order_is_paid(self):
        self.assertEqual(osync.collectible_balance(OWED_CURRENT, OWED_NET, False), 0.0)

    def test_credit_from_zero_dollar_refunds_means_nothing_to_collect(self):
        self.assertEqual(osync.collectible_balance(CURRENT_TOTAL, NET_PAYMENT, True), 0.0)

    def test_balance_is_current_total_minus_payments(self):
        self.assertEqual(osync.collectible_balance(OWED_CURRENT, OWED_NET, True), 12.0)

    def test_sub_cent_balance_is_zero(self):
        self.assertEqual(osync.collectible_balance(100.004, 100.0, True), 0.0)

    def test_unparseable_amounts_are_zero(self):
        self.assertEqual(osync.collectible_balance("n/a", None, True), 0.0)


if __name__ == "__main__":
    unittest.main()
