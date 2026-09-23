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
            "tracking": False, "shipping_lines": 0, "mark_paid": 0.0, "unsupported": 0, "variant_prices": 0,
            "create_products": 0,
        })


MISSING_BARCODE = "0002"
NEW_VARIANT_ID = "gid://shopify/ProductVariant/2"
NEW_PRODUCT_ID = "gid://shopify/Product/2"


def _empty_order():
    return {"id": "gid://shopify/Order/1", "tracking_numbers": ["1Z1"],
            "fulfillment_ids_without_tracking": [], "outstanding": 0, "lines": []}


def _invoice_only(qty=3.0, unit_price=16.6):
    return {"tracking_no": "1Z1",
            "lines": [{"key": MISSING_BARCODE, "barcode": MISSING_BARCODE, "sku": "SW-10",
                       "description": "Swisher Sweets Leaf 10/3pk", "qty_shipped": qty,
                       "unit_price": unit_price}]}


class CreateProductActionTests(unittest.TestCase):
    """A BackOffice line whose UPC carries no Shopify variant."""

    def test_toggle_off_still_reports_the_line_unsupported(self):
        plan = osync.plan_order_fix(_empty_order(), _invoice_only(), {})
        self.assertEqual(plan["actions"], [])
        self.assertEqual([u["reason"] for u in plan["unsupported"]], ["no_variant"])
        self.assertTrue(plan["noop"])

    def test_toggle_on_plans_the_product_from_items_tbl_then_the_line(self):
        plan = osync.plan_order_fix(
            _empty_order(), _invoice_only(), {}, create_products=True,
            item_prices={MISSING_BARCODE: {"description": "Swisher Sweets Leaf 10/3pk $2.49 Original",
                                           "unit_price": 18.99, "unit_cost": 12.25}})
        self.assertEqual(_kinds(plan), ["create_product", "add"])
        self.assertEqual(plan["unsupported"], [])
        self.assertEqual(plan["notes"], [])
        self.assertEqual(plan["actions"][0], {
            "kind": "create_product", "reason": "create", "key": MISSING_BARCODE,
            "barcode": MISSING_BARCODE, "description": "Swisher Sweets Leaf 10/3pk $2.49 Original",
            "title": "Swisher Sweets Leaf 10/3pk $2.49 Original", "sku": "SW-10",
            "unit_price": 18.99, "unit_cost": 12.25, "price_source": "items_tbl",
        })
        add = plan["actions"][1]
        # The line goes on at the INVOICE price, not the storefront price.
        self.assertEqual((add["qty"], add["unit_price"], add["create_variant"]), (3, 16.6, True))
        self.assertIsNone(add["variant_id"])
        self.assertEqual(plan["summary"]["create_products"], 1)

    def test_upc_absent_from_items_tbl_is_created_from_the_invoice_line(self):
        plan = osync.plan_order_fix(_empty_order(), _invoice_only(), {},
                                    create_products=True, item_prices={})
        create = plan["actions"][0]
        self.assertEqual((create["title"], create["unit_price"], create["price_source"]),
                         ("Swisher Sweets Leaf 10/3pk", 16.6, "invoice"))
        self.assertIsNone(create["unit_cost"])
        self.assertEqual(_reasons(plan), ["not_found"])

    def test_item_lookup_failure_is_a_note_not_a_blocker(self):
        plan = osync.plan_order_fix(_empty_order(), _invoice_only(), {}, create_products=True,
                                    item_prices=None, item_price_error="timeout")
        self.assertEqual(_kinds(plan), ["create_product", "add"])
        self.assertEqual(_reasons(plan), ["lookup_failed"])
        self.assertIn("timeout", plan["notes"][0]["message"])

    def test_zero_item_price_falls_back_to_the_invoice_price(self):
        plan = osync.plan_order_fix(
            _empty_order(), _invoice_only(), {}, create_products=True,
            item_prices={MISSING_BARCODE: {"description": "From Items", "unit_price": 0}})
        create = plan["actions"][0]
        self.assertEqual((create["title"], create["unit_price"], create["price_source"]),
                         ("From Items", 16.6, "invoice"))
        self.assertEqual(_reasons(plan), ["no_price"])

    def test_a_line_without_a_barcode_is_never_created(self):
        invoice = {"tracking_no": "1Z1",
                   "lines": [{"key": "desc:widget", "barcode": "", "sku": "", "description": "Widget",
                              "qty_shipped": 1.0, "unit_price": 5.0}]}
        plan = osync.plan_order_fix(_empty_order(), invoice, {}, create_products=True)
        self.assertEqual(plan["actions"], [])
        self.assertEqual([u["reason"] for u in plan["unsupported"]], ["no_barcode"])

    def test_created_line_skips_the_storefront_price_step(self):
        # A repriced line whose variant vanished from the catalog: the new
        # product already carries Items_tbl.UnitPrice, so no variant_price.
        plan = osync.plan_order_fix(_order(), _invoice(), {}, create_products=True,
                                    item_prices={BARCODE: {"description": "Widget", "unit_price": ITEM_PRICE}})
        self.assertEqual(_kinds(plan), ["refund", "create_product", "add"])
        self.assertEqual(plan["notes"], [])


class ResolveCreatedVariantsTests(unittest.TestCase):
    def _plan(self, invoice_price):
        return osync.plan_order_fix(
            _empty_order(), _invoice_only(unit_price=invoice_price), {}, create_products=True,
            item_prices={MISSING_BARCODE: {"description": "Widget", "unit_price": 18.99}})

    def _created(self, price):
        return {MISSING_BARCODE: {"variant_id": NEW_VARIANT_ID, "product_id": NEW_PRODUCT_ID,
                                  "price": price, "price_raw": f"{price:.2f}",
                                  "product_title": "Widget"}}

    def test_created_above_the_invoice_price_takes_a_per_unit_discount(self):
        plan = self._plan(16.6)
        self.assertEqual(osync.resolve_created_variants(plan["actions"], self._created(18.99)), [])
        add = plan["actions"][1]
        self.assertEqual(add["variant_id"], NEW_VARIANT_ID)
        self.assertEqual(add["product_id"], NEW_PRODUCT_ID)
        self.assertEqual(add["variant_price"], 18.99)
        self.assertEqual(add["variant_price_raw"], "18.99")
        self.assertFalse(add["bump_price"])
        self.assertEqual(add["discount_total"], round((18.99 - 16.6) * 3, 2))

    def test_created_below_the_invoice_price_bumps_instead(self):
        plan = self._plan(20.0)
        osync.resolve_created_variants(plan["actions"], self._created(18.99))
        add = plan["actions"][1]
        self.assertTrue(add["bump_price"])
        self.assertEqual(add["discount_total"], 0.0)

    def test_created_at_the_invoice_price_needs_neither(self):
        plan = self._plan(18.99)
        osync.resolve_created_variants(plan["actions"], self._created(18.99))
        add = plan["actions"][1]
        self.assertFalse(add["bump_price"])
        self.assertEqual(add["discount_total"], 0.0)

    def test_a_barcode_that_did_not_come_back_is_reported(self):
        plan = self._plan(16.6)
        self.assertEqual(osync.resolve_created_variants(plan["actions"], {}), [MISSING_BARCODE])
        self.assertIsNone(plan["actions"][1]["variant_id"])


if __name__ == "__main__":
    unittest.main()
