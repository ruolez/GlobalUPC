"""
Pure matching tests for order_sync_helper.match_orders (no database, no network).

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

BASKET = ["0001", "0002", "0003", "0004", "0005"]
OTHER_BASKET = ["0101", "0102", "0103", "0104", "0105"]
PHONE = "6095765057"
ADDRESS = "2510 Atlantic Ave"
ZIP = "08401"
UNIT_PRICE = 10.0
LATE_DAYS = 4


def _order(order_id="o1", date="2026-08-31", barcodes=BASKET, tracking=(), phones=(PHONE,),
           address1=ADDRESS, zip_code=ZIP, name="Sunny Sunny"):
    return {
        "id": f"gid://shopify/Order/{order_id}", "name": f"FSD{order_id}", "local_date": date,
        "total": UNIT_PRICE * len(barcodes), "tracking_numbers": list(tracking),
        "phones": list(phones), "address1": address1, "zip": zip_code, "customer_name": name,
        "lines": [{
            "line_item_id": f"gid://shopify/LineItem/{b}", "barcode": b, "sku": "", "title": f"Item {b}",
            "quantity": 1, "current_quantity": 1, "refundable_quantity": 1, "discounted_total": UNIT_PRICE,
        } for b in barcodes],
    }


def _invoice(invoice_id=1, date="2026-08-27", barcodes=BASKET, tracking="", phone=PHONE,
             address1=ADDRESS, zip_code=ZIP, business="MOBIL FOODMART"):
    return {
        "invoice_id": invoice_id, "invoice_number": str(90000 + invoice_id), "date": date,
        "total": UNIT_PRICE * len(barcodes), "tracking_no": tracking, "has_tracking": bool(tracking),
        "in_range": True, "ship_phone": phone, "ship_address1": address1, "ship_zip": zip_code,
        "ship_to": business, "ship_contact": "", "business_name": business,
        "lines": [{"key": b, "barcode": b, "sku": "", "description": f"Item {b}",
                   "qty_shipped": 1.0, "unit_price": UNIT_PRICE} for b in barcodes],
    }


def _pairs(result):
    return [(m["orders"][0]["name"], m["invoices"][0]["invoice_number"], m["method"], m["ambiguous"])
            for m in result["matches"]]


class LateIdentityBasketTests(unittest.TestCase):
    def test_late_order_pairs_on_shared_address_and_identical_basket(self):
        result = osync.match_orders([_order(phones=())], [_invoice(phone="")])
        self.assertEqual(_pairs(result), [("FSDo1", "90001", "identity_basket", False)])
        self.assertEqual((result["unmatched_orders"], result["unmatched_invoices"]), ([], []))

    def test_late_order_pairs_on_shared_phone_when_address_differs(self):
        result = osync.match_orders([_order(address1="1 Other St")], [_invoice()])
        self.assertEqual(_pairs(result), [("FSDo1", "90001", "identity_basket", False)])

    def test_identical_basket_without_any_identity_key_stays_unmatched(self):
        order = _order(phones=(), address1="1 Other St", zip_code="99999", name="Someone Else")
        result = osync.match_orders([order], [_invoice()])
        self.assertEqual(_pairs(result), [])
        self.assertEqual(len(result["unmatched_orders"]), 1)

    def test_shared_identity_with_a_different_basket_stays_unmatched(self):
        result = osync.match_orders([_order(barcodes=OTHER_BASKET)], [_invoice()])
        self.assertEqual(_pairs(result), [])

    def test_conflicting_tracking_numbers_block_the_late_pair(self):
        result = osync.match_orders([_order(tracking=("1Z1",))], [_invoice(tracking="1Z2")])
        self.assertEqual(_pairs(result), [])

    def test_closest_invoice_date_wins_among_identical_weekly_baskets(self):
        near = _invoice(invoice_id=1, date="2026-08-27")
        far = _invoice(invoice_id=2, date="2026-08-20")
        result = osync.match_orders([_order()], [far, near])
        self.assertEqual(_pairs(result), [("FSDo1", "90001", "identity_basket", False)])
        self.assertEqual([i["invoice_id"] for i in result["unmatched_invoices"]], [2])

    def test_two_invoices_at_the_same_lag_are_flagged_ambiguous(self):
        before = _invoice(invoice_id=1, date="2026-08-27")
        after = _invoice(invoice_id=2, date="2026-09-04")
        result = osync.match_orders([_order()], [before, after])
        self.assertEqual([p[2:] for p in _pairs(result)], [("identity_basket", True)])

    def test_order_entered_with_part_of_the_invoice_pairs_on_shared_identity(self):
        # 53 of 67 lines seen live: every order line on the invoice, order covers 79 % of it
        invoice_lines = [f"{n:04d}" for n in range(1, 68)]
        order = _order(barcodes=invoice_lines[:53])
        result = osync.match_orders([order], [_invoice(barcodes=invoice_lines)])
        self.assertEqual(_pairs(result), [("FSDo1", "90001", "identity_basket", False)])

    def test_small_reorder_inside_a_big_invoice_stays_unmatched(self):
        invoice_lines = [f"{n:04d}" for n in range(1, 68)]
        result = osync.match_orders([_order(barcodes=invoice_lines[:2])], [_invoice(barcodes=invoice_lines)])
        self.assertEqual(_pairs(result), [])

    def test_partial_order_without_identity_stays_unmatched(self):
        invoice_lines = [f"{n:04d}" for n in range(1, 68)]
        order = _order(barcodes=invoice_lines[:53], phones=(), address1="1 Other St", zip_code="99999", name="Someone Else")
        result = osync.match_orders([order], [_invoice(barcodes=invoice_lines)])
        self.assertEqual(_pairs(result), [])

    def test_order_with_lines_the_invoice_lacks_is_not_a_subset(self):
        invoice_lines = [f"{n:04d}" for n in range(1, 68)]
        order = _order(barcodes=invoice_lines[:40] + OTHER_BASKET)
        result = osync.match_orders([order], [_invoice(barcodes=invoice_lines)])
        self.assertEqual(_pairs(result), [])

    def test_relabelled_box_pairs_when_day_basket_and_total_agree(self):
        order = _order(date="2026-09-08", tracking=("SP2512680387",))
        invoice = _invoice(date="2026-09-08", tracking="SP2572623794")
        result = osync.match_orders([order], [invoice])
        self.assertEqual(_pairs(result), [("FSDo1", "90001", "phone", False)])
        self.assertTrue(osync.tracking_conflict([order], [invoice]))

    def test_different_tracking_with_a_day_lag_still_blocks(self):
        order = _order(date="2026-09-12", tracking=("SP2512680387",))
        result = osync.match_orders([order], [_invoice(date="2026-09-08", tracking="SP2572623794")])
        self.assertEqual(_pairs(result), [])

    def test_different_tracking_with_a_different_total_still_blocks(self):
        order = _order(date="2026-09-08", tracking=("SP2512680387",))
        order["total"] = order["total"] * 1.1
        result = osync.match_orders([order], [_invoice(date="2026-09-08", tracking="SP2572623794")])
        self.assertEqual(_pairs(result), [])

    def test_shared_tracking_pair_is_not_flagged(self):
        order = _order(date="2026-09-08", tracking=("1Z1",))
        invoice = _invoice(date="2026-09-08", tracking="1Z1")
        self.assertFalse(osync.tracking_conflict([order], [invoice]))

    def test_same_day_pair_is_still_claimed_by_the_identity_pass(self):
        result = osync.match_orders([_order(date="2026-08-27")], [_invoice()])
        self.assertEqual(_pairs(result), [("FSDo1", "90001", "phone", False)])

    def test_late_pass_does_not_steal_an_invoice_from_a_tracking_match(self):
        tracked = _order(order_id="t", date="2026-08-27", tracking=("1Z1",), phones=(), address1="9 Elsewhere Rd")
        late = _order(order_id="l")
        result = osync.match_orders([late, tracked], [_invoice(tracking="1Z1")])
        self.assertEqual(_pairs(result), [("FSDt", "90001", "tracking", False)])
        self.assertEqual([o["name"] for o in result["unmatched_orders"]], ["FSDl"])


SHIP_PRICE = 15.0


def _ship_order_line(price=SHIP_PRICE):
    return {"line_item_id": "gid://shopify/LineItem/ship", "barcode": "ship", "sku": "shipment",
            "title": "Shipping", "quantity": 1, "current_quantity": 1, "refundable_quantity": 1,
            "discounted_total": price}


def _ship_invoice_line(price=SHIP_PRICE):
    return {"key": "ship", "barcode": "ship", "sku": "shipment", "description": "Shipping & Handling",
            "qty_shipped": 1.0, "unit_price": price}


SHIPPING_LINE_ID = "gid://shopify/ShippingLine/1"


def _shipping_line(price=SHIP_PRICE, title="Standard Shipping"):
    return {"id": SHIPPING_LINE_ID, "title": title, "price": price}


def _issue(diffs, key):
    return next(d["issues"] for d in diffs if d["key"] == key)


class ShippingLineTests(unittest.TestCase):
    def test_invoice_shipping_with_no_shopify_shipping_is_missing_in_shopify(self):
        invoice = _invoice()
        invoice["lines"].append(_ship_invoice_line())
        kinds, diffs = osync.compare_lines(_order(), invoice)
        self.assertEqual((kinds, _issue(diffs, "ship")), (["product"], ["missing_in_shopify"]))

    def test_shipping_item_price_difference_is_a_price_issue(self):
        order = _order()
        order["lines"].append(_ship_order_line(SHIP_PRICE))
        invoice = _invoice()
        invoice["lines"].append(_ship_invoice_line(SHIP_PRICE - 2.5))
        kinds, diffs = osync.compare_lines(order, invoice)
        self.assertEqual((kinds, _issue(diffs, "ship")), (["price"], ["price"]))

    def test_shopify_shipping_line_compares_like_the_shipping_item(self):
        order = _order()
        order["shipping_lines"] = [_shipping_line(SHIP_PRICE)]
        invoice = _invoice()
        invoice["lines"].append(_ship_invoice_line(SHIP_PRICE))
        kinds, diffs = osync.compare_lines(order, invoice)
        ship = next(d for d in diffs if d["key"] == "ship")
        self.assertEqual((kinds, ship["issues"], ship["sh_qty"], ship["sh_unit_price"]), ([], [], 1.0, SHIP_PRICE))

    def test_zero_priced_shipping_line_counts_as_no_shipping(self):
        order = _order()
        order["shipping_lines"] = [_shipping_line(0.0)]
        self.assertNotIn("ship", osync._shopify_lines_by_key(order))

    def test_shipping_line_form_is_fixed_by_replacing_the_shipping_line(self):
        order = _order()
        order["shipping_lines"] = [_shipping_line(SHIP_PRICE - 2.5)]
        invoice = _invoice()
        invoice["lines"].append(_ship_invoice_line(SHIP_PRICE))
        plan = osync.plan_order_fix(order, invoice, {}, push_tracking=False)
        self.assertEqual(plan["actions"], [{
            "kind": "shipping_line", "reason": "shipping", "key": "ship", "barcode": "ship",
            "description": "Shipping & Handling", "title": "Standard Shipping",
            "remove_ids": [SHIPPING_LINE_ID], "sh_amount": SHIP_PRICE - 2.5,
            "amount": SHIP_PRICE, "unit_price": SHIP_PRICE,
        }])
        self.assertEqual(plan["summary"]["shipping_lines"], 1)

    def test_shipping_line_with_no_invoice_shipping_is_removed(self):
        order = _order()
        order["shipping_lines"] = [_shipping_line(SHIP_PRICE)]
        plan = osync.plan_order_fix(order, _invoice(), {}, push_tracking=False)
        self.assertEqual([(a["kind"], a["reason"], a["amount"], a["remove_ids"]) for a in plan["actions"]],
                         [("shipping_line", "shipping_remove", None, [SHIPPING_LINE_ID])])

    def test_shipping_item_form_is_repriced_like_a_product_without_a_store_price_step(self):
        order = _order()
        order["lines"].append(_ship_order_line(SHIP_PRICE - 2.5))
        invoice = _invoice()
        invoice["lines"].append(_ship_invoice_line(SHIP_PRICE))
        variants = {"ship": {"variant_id": "gid://shopify/ProductVariant/ship", "product_id": "gid://shopify/Product/ship",
                             "price": SHIP_PRICE - 2.5, "price_raw": f"{SHIP_PRICE - 2.5:.2f}", "product_title": "Shipping"}}
        plan = osync.plan_order_fix(order, invoice, variants, push_tracking=False,
                                    item_prices={"ship": {"unit_price": 1.0}})
        self.assertEqual([(a["kind"], a["reason"], a["key"]) for a in plan["actions"]],
                         [("refund", "replace", "ship"), ("add", "replace", "ship")])
        self.assertEqual(plan["notes"], [])

    def test_shipping_line_does_not_count_toward_basket_overlap(self):
        order = _order(barcodes=OTHER_BASKET)
        order["lines"].append(_ship_order_line())
        invoice = _invoice(barcodes=OTHER_BASKET[:1] + BASKET[:4])
        invoice["lines"].append(_ship_invoice_line())
        self.assertEqual(osync._line_jaccard(order, invoice), 1 / 9)

    def test_shipping_never_counts_toward_matching_keys(self):
        order = _order()
        order["shipping_lines"] = [_shipping_line()]
        invoice = _invoice()
        invoice["lines"].append(_ship_invoice_line())
        self.assertEqual((osync._line_keys(order, True), osync._line_keys(invoice, False)), (set(BASKET), set(BASKET)))


if __name__ == "__main__":
    unittest.main()
