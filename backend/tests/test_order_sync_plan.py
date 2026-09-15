"""
Pure planner tests for order_sync_helper.plan_order_fix (no database, no network).

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The planner never touches MSSQL; keep the import safe on hosts without pyodbc.
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

import order_sync_helper as osync  # noqa: E402

BARCODE = "0001"
VARIANT_ID = "gid://shopify/ProductVariant/1"
PRODUCT_ID = "gid://shopify/Product/1"
STORE_PRICE = 10.0
INVOICE_PRICE = 9.5
ITEM_PRICE = 10.1


def _order(qty=2, unit_price=STORE_PRICE):
    return {
        "id": "gid://shopify/Order/1", "tracking_numbers": ["1Z1"],
        "fulfillment_ids_without_tracking": [], "outstanding": 0,
        "lines": [{
            "line_item_id": "gid://shopify/LineItem/1", "barcode": BARCODE, "sku": "", "title": "Widget",
            "quantity": qty, "current_quantity": qty, "refundable_quantity": qty,
            "discounted_total": round(qty * unit_price, 2),
        }],
    }


def _invoice(qty=2.0, unit_price=INVOICE_PRICE):
    return {
        "tracking_no": "1Z1",
        "lines": [{"key": BARCODE, "barcode": BARCODE, "sku": "", "description": "Widget",
                   "qty_shipped": qty, "unit_price": unit_price}],
    }


VARIANTS = {BARCODE: {"variant_id": VARIANT_ID, "product_id": PRODUCT_ID, "price": STORE_PRICE,
                      "price_raw": f"{STORE_PRICE:.2f}", "product_title": "Widget"}}


def _kinds(plan):
    return [a["kind"] for a in plan["actions"]]


def _reasons(plan):
    return [n["reason"] for n in plan["notes"]]


class VariantPriceActionTests(unittest.TestCase):
    def test_repriced_line_plans_storefront_price_from_item_price(self):
        plan = osync.plan_order_fix(_order(), _invoice(), VARIANTS,
                                    item_prices={BARCODE: {"unit_price": ITEM_PRICE}})
        self.assertEqual(_kinds(plan), ["refund", "add", "variant_price"])
        self.assertEqual(plan["actions"][2], {
            "kind": "variant_price", "reason": "price", "key": BARCODE,
            "barcode": BARCODE, "description": "Widget",
            "variant_id": VARIANT_ID, "product_id": PRODUCT_ID,
            "variant_price": STORE_PRICE, "variant_price_raw": f"{STORE_PRICE:.2f}",
            "unit_price": ITEM_PRICE,
        })
        self.assertEqual(plan["notes"], [])
        self.assertEqual(plan["summary"]["variant_prices"], 1)
        self.assertFalse(plan["noop"])

    def test_lookup_failure_notes_and_still_reprices_the_order_line(self):
        plan = osync.plan_order_fix(_order(), _invoice(), VARIANTS,
                                    item_prices=None, item_price_error="timeout")
        self.assertEqual(_kinds(plan), ["refund", "add"])
        self.assertEqual(_reasons(plan), ["lookup_failed"])
        self.assertIn("timeout", plan["notes"][0]["message"])
        self.assertEqual(plan["summary"]["variant_prices"], 0)
        self.assertFalse(plan["noop"])

    def test_upc_missing_from_items_tbl_is_noted(self):
        plan = osync.plan_order_fix(_order(), _invoice(), VARIANTS, item_prices={})
        self.assertEqual(_kinds(plan), ["refund", "add"])
        self.assertEqual(_reasons(plan), ["not_found"])

    def test_empty_or_zero_item_price_is_noted(self):
        for bad in (None, 0, 0.0):
            with self.subTest(unit_price=bad):
                plan = osync.plan_order_fix(_order(), _invoice(), VARIANTS,
                                            item_prices={BARCODE: {"unit_price": bad}})
                self.assertEqual(_kinds(plan), ["refund", "add"])
                self.assertEqual(_reasons(plan), ["no_price"])

    def test_item_price_within_tolerance_of_store_price_is_unchanged(self):
        plan = osync.plan_order_fix(_order(), _invoice(), VARIANTS,
                                    item_prices={BARCODE: {"unit_price": STORE_PRICE + 0.004}})
        self.assertEqual(_kinds(plan), ["refund", "add"])
        self.assertEqual(_reasons(plan), ["unchanged"])

    def test_quantity_only_difference_leaves_storefront_price_alone(self):
        plan = osync.plan_order_fix(_order(qty=2), _invoice(qty=3.0, unit_price=STORE_PRICE), VARIANTS,
                                    item_prices={BARCODE: {"unit_price": ITEM_PRICE}})
        self.assertEqual(_kinds(plan), ["add"])
        self.assertEqual(plan["notes"], [])

    def test_unsupported_price_line_gets_neither_action_nor_note(self):
        plan = osync.plan_order_fix(_order(), _invoice(), {},
                                    item_prices={BARCODE: {"unit_price": ITEM_PRICE}})
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["notes"], [])
        self.assertEqual([u["reason"] for u in plan["unsupported"]], ["no_variant"])
        self.assertTrue(plan["noop"])

    def test_default_arguments_keep_the_previous_plan_shape(self):
        plan = osync.plan_order_fix(_order(), _invoice(), VARIANTS)
        self.assertEqual(_kinds(plan), ["refund", "add"])
        self.assertEqual(plan["notes"], [])
        self.assertEqual(plan["summary"], {
            "refunds": 1, "refund_units": 2, "adds": 1, "add_units": 2, "add_amount": 19.0,
            "tracking": False, "mark_paid": 0.0, "unsupported": 0, "variant_prices": 0,
        })


if __name__ == "__main__":
    unittest.main()
