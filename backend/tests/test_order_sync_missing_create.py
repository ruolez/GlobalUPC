"""
Creating the products a BackOffice-only invoice needs (no database, no network):
order_sync_helper.plan_missing_creates and the automation's report math for it.

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

import order_sync_auto as auto  # noqa: E402
import order_sync_helper as osync  # noqa: E402

MISSING = "810134928169"
DRAFT = "842426164221"
SKU = "pblazywrapsthlem"
LINE_DESC = "Blazy Susan Wraps, 25 x 2ct Tea Honey Lemon"
ITEM_DESC = "Blazy Susan Wraps 25x2 Tea Honey Lemon"
ITEM_PRICE = 21.5
ITEM_COST = 18.25
OLD_INVOICE_PRICE = 20.0
NEW_INVOICE_PRICE = 22.0


def _line(barcode, price, qty=3.0, sku=SKU, description=LINE_DESC):
    return {"barcode": barcode, "sku": sku, "description": description, "qty": qty, "unit_price": price}


def _order(number, date, lines):
    return {"invoice_number": number, "date": date, "customer": "ATVSS Inc.", "lines": lines}


def _missing(barcode=MISSING, status="MISSING", invoices=("94208",)):
    return {"barcode": barcode, "sku": SKU, "description": LINE_DESC, "shopify_status": status,
            "shopify_title": None, "invoice_count": len(invoices), "total_qty": 3.0,
            "invoices": list(invoices), "last_date": "2026-10-23"}


ITEM = {"description": ITEM_DESC, "unit_price": ITEM_PRICE, "unit_cost": ITEM_COST}


class PlanMissingCreatesTests(unittest.TestCase):
    def test_missing_barcode_is_created_from_the_backoffice_item(self):
        orders = [_order("94208", "2026-10-23", [_line(MISSING, NEW_INVOICE_PRICE)])]
        actions, skipped = osync.plan_missing_creates([_missing()], orders, {MISSING: ITEM}, None)
        self.assertEqual((actions, skipped), ([{
            "kind": "create_product", "reason": "create", "key": MISSING,
            "barcode": MISSING, "description": ITEM_DESC, "title": ITEM_DESC, "sku": SKU,
            "unit_price": ITEM_PRICE, "unit_cost": ITEM_COST, "price_source": "items_tbl",
            "invoices": ["94208"], "note": None,
        }], []))

    def test_without_an_item_price_the_latest_invoice_price_is_used(self):
        orders = [_order("94100", "2026-10-02", [_line(MISSING, OLD_INVOICE_PRICE)]),
                  _order("94208", "2026-10-23", [_line(MISSING, NEW_INVOICE_PRICE)])]
        actions, _skipped = osync.plan_missing_creates(
            [_missing(invoices=("94100", "94208"))], orders, {}, None)
        self.assertEqual([(a["unit_price"], a["price_source"], a["title"], a["note"]) for a in actions],
                         [(NEW_INVOICE_PRICE, "invoice", LINE_DESC,
                           osync.CREATE_PRODUCT_MESSAGES["not_found"])])

    def test_failed_item_lookup_still_creates_from_the_invoice(self):
        orders = [_order("94208", "2026-10-23", [_line(MISSING, NEW_INVOICE_PRICE)])]
        actions, _skipped = osync.plan_missing_creates([_missing()], orders, None, "timeout")
        self.assertEqual([(a["unit_price"], a["note"]) for a in actions],
                         [(NEW_INVOICE_PRICE, osync.CREATE_PRODUCT_MESSAGES["lookup_failed"])])

    def test_barcode_on_an_inactive_product_is_not_created(self):
        orders = [_order("94208", "2026-10-23", [_line(DRAFT, NEW_INVOICE_PRICE)])]
        actions, skipped = osync.plan_missing_creates(
            [_missing(DRAFT, "DRAFT")], orders, {DRAFT: ITEM}, None)
        self.assertEqual((actions, skipped), ([], [{
            "barcode": DRAFT, "invoices": ["94208"], "reason": "inactive",
            "message": osync.MISSING_CREATE_MESSAGES["inactive"].format(status="draft"),
        }]))

    def test_barcode_without_any_price_is_not_created(self):
        orders = [_order("94208", "2026-10-23", [_line(MISSING, 0.0)])]
        actions, skipped = osync.plan_missing_creates([_missing()], orders, {}, None)
        self.assertEqual((actions, [s["reason"] for s in skipped]), ([], ["no_price"]))


class BackofficeOnlyOrdersTests(unittest.TestCase):
    def test_invoice_price_is_carried_for_product_creation(self):
        rows = [{"status": "backoffice_unmatched", "bo_invoice_number": "94208", "bo_date": "2026-10-23",
                 "bo_customer": "ATVSS Inc.",
                 "line_diffs": [{"barcode": MISSING, "sku": SKU, "description": LINE_DESC,
                                 "bo_qty": 3.0, "bo_unit_price": NEW_INVOICE_PRICE}]},
                {"status": "matched_ok", "bo_invoice_number": "94207", "line_diffs": []}]
        self.assertEqual(auto.backoffice_only_orders(rows), [_order(
            "94208", "2026-10-23", [_line(MISSING, NEW_INVOICE_PRICE)])])


class MissingCreateReportTests(unittest.TestCase):
    def _report(self, *actions):
        return {"missing_products": [{"barcode": str(i), "action": a} for i, a in enumerate(actions)],
                "created_products": [{"barcode": "0"}] if "created" in actions else []}

    def test_counts_split_created_would_create_and_failed(self):
        counts = auto.report_counts(self._report("created", "would_create", "would_create", "failed", "skipped"))
        self.assertEqual({k: counts[k] for k in ("created_products", "would_create", "create_failed",
                                                  "missing_products")},
                         {"created_products": 1, "would_create": 2, "create_failed": 1, "missing_products": 5})

    def test_a_failed_creation_makes_the_run_partial(self):
        self.assertEqual(auto.final_status(auto.report_counts(self._report("failed")), False), "partial")


if __name__ == "__main__":
    unittest.main()
