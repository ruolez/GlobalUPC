"""
Pure tests for order_sync_helper.aggregate_missing_products (no database, no network).

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

MISSING = "0001"
ACTIVE = "0002"
ARCHIVED = "0003"
QTY_A = 3.0
QTY_B = 2.0


def _line(barcode, qty, description="Item", sku="sku"):
    return {"barcode": barcode, "sku": sku, "description": description, "qty": qty}


def _order(number, date, lines):
    return {"invoice_number": number, "date": date, "customer": "Store", "lines": lines}


FOUND = {
    ACTIVE: {"product_status": "ACTIVE", "product_title": "Active product"},
    ARCHIVED: {"product_status": "ARCHIVED", "product_title": "Old product"},
}


class AggregateMissingProductsTests(unittest.TestCase):
    def test_active_catalog_products_are_not_listed(self):
        rows = osync.aggregate_missing_products([_order("1", "2026-09-01", [_line(ACTIVE, QTY_A)])], FOUND)
        self.assertEqual(rows, [])

    def test_missing_barcode_is_aggregated_across_invoices(self):
        orders = [
            _order("1", "2026-09-01", [_line(MISSING, QTY_A, "Widget"), _line(MISSING, QTY_B, "Widget")]),
            _order("2", "2026-09-03", [_line(MISSING, QTY_B, "Widget")]),
        ]
        self.assertEqual(osync.aggregate_missing_products(orders, FOUND), [{
            "barcode": MISSING, "sku": "sku", "description": "Widget",
            "shopify_status": "MISSING", "shopify_title": None,
            "invoice_count": 2, "total_qty": QTY_A + QTY_B + QTY_B,
            "invoices": ["1", "2"], "last_date": "2026-09-03",
        }])

    def test_archived_product_is_listed_with_its_status_and_title(self):
        rows = osync.aggregate_missing_products([_order("1", "2026-09-01", [_line(ARCHIVED, QTY_A)])], FOUND)
        self.assertEqual([(r["barcode"], r["shopify_status"], r["shopify_title"]) for r in rows],
                         [(ARCHIVED, "ARCHIVED", "Old product")])

    def test_shipping_and_blank_barcode_lines_are_skipped(self):
        lines = [_line("ship", 1, "Shipping & Handling", "shipment"), _line("", QTY_A, "No UPC", "")]
        self.assertEqual(osync.aggregate_missing_products([_order("1", "2026-09-01", lines)], {}), [])

    def test_sorted_by_invoice_count_then_units(self):
        orders = [
            _order("1", "2026-09-01", [_line("0009", QTY_A), _line("0008", QTY_B)]),
            _order("2", "2026-09-02", [_line("0008", QTY_B)]),
        ]
        rows = osync.aggregate_missing_products(orders, {})
        self.assertEqual([r["barcode"] for r in rows], ["0008", "0009"])


if __name__ == "__main__":
    unittest.main()
