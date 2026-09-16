"""
Serialization of price-bumped order edits in order_sync_fix_helper.add_lines
(no database, no network — the Shopify calls are stubbed).

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import asyncio
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

import order_sync_fix_helper as ofix  # noqa: E402

VARIANT = "gid://shopify/ProductVariant/1"
PRODUCT = "gid://shopify/Product/1"
STORE_PRICE = "53.50"
INVOICE_PRICE_A = 56.5
INVOICE_PRICE_B = 53.55


def _add(unit_price, bump=True):
    return {"barcode": "0001", "qty": 1, "unit_price": unit_price, "bump_price": bump,
            "product_id": PRODUCT, "variant_id": VARIANT, "variant_price_raw": STORE_PRICE}


class FakeStore:
    """Stands in for Shopify: a variant price plus a log of every bump /
    restore / add, and a switch that makes the edit yield mid-way so a
    concurrent edit gets the chance to interleave."""

    def __init__(self):
        self.price = float(STORE_PRICE)
        self.log = []

    async def set_price(self, ctx, product_id, variant_id, price, step="edit"):
        self.price = float(price)
        self.log.append(("set", float(price)))

    async def read_price(self, ctx, variant_id):
        return self.price

    async def add_lines(self, ctx, order_gid, adds, note, bumped):
        for a in adds:
            if a.get("bump_price"):
                await ofix._bump_variant_price(ctx, a, float(a["unit_price"]), bumped)
            await asyncio.sleep(0)          # let the other order run if it can
            self.log.append(("add", order_gid, self.price))
        return {"added": adds, "outstanding": 0.0, "open_fulfillment_order_ids": [], "calculated_order_id": "c"}


class BumpSerializationTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self._orig = (ofix.set_variant_price, ofix._read_variant_price, ofix._add_lines, ofix._BUMP_READBACK_DELAY_SECONDS)
        ofix.set_variant_price = self.store.set_price
        ofix._read_variant_price = self.store.read_price
        ofix._add_lines = self.store.add_lines
        ofix._BUMP_READBACK_DELAY_SECONDS = 0

    def tearDown(self):
        ofix.set_variant_price, ofix._read_variant_price, ofix._add_lines, ofix._BUMP_READBACK_DELAY_SECONDS = self._orig

    def test_concurrent_bumped_edits_each_add_at_their_own_price(self):
        async def run():
            return await asyncio.gather(
                ofix.add_lines(None, "order-a", [_add(INVOICE_PRICE_A)], "n"),
                ofix.add_lines(None, "order-b", [_add(INVOICE_PRICE_B)], "n"),
            )
        asyncio.run(run())
        adds = [e for e in self.store.log if e[0] == "add"]
        self.assertEqual(adds, [("add", "order-a", INVOICE_PRICE_A), ("add", "order-b", INVOICE_PRICE_B)])
        self.assertEqual(self.store.log, [
            ("set", INVOICE_PRICE_A), ("add", "order-a", INVOICE_PRICE_A), ("set", float(STORE_PRICE)),
            ("set", INVOICE_PRICE_B), ("add", "order-b", INVOICE_PRICE_B), ("set", float(STORE_PRICE)),
        ])

    def test_price_is_restored_even_when_the_edit_fails(self):
        async def failing(ctx, order_gid, adds, note, bumped):
            await ofix._bump_variant_price(ctx, adds[0], float(adds[0]["unit_price"]), bumped)
            raise ofix.FixStepError("edit", "boom")
        ofix._add_lines = failing
        with self.assertRaises(ofix.FixStepError):
            asyncio.run(ofix.add_lines(None, "order-a", [_add(INVOICE_PRICE_A)], "n"))
        self.assertEqual(self.store.log, [("set", INVOICE_PRICE_A), ("set", float(STORE_PRICE))])

    def test_bump_that_never_settles_is_abandoned_before_the_add(self):
        async def stale(ctx, variant_id):
            return float(STORE_PRICE)
        ofix._read_variant_price = stale
        with self.assertRaises(ofix.FixStepError) as cm:
            asyncio.run(ofix.add_lines(None, "order-a", [_add(INVOICE_PRICE_A)], "n"))
        self.assertIn("did not settle", str(cm.exception))
        self.assertEqual([e for e in self.store.log if e[0] == "add"], [])
        self.assertEqual(self.store.log[-1], ("set", float(STORE_PRICE)))

    def test_edit_without_a_bump_skips_the_lock_and_the_catalog(self):
        asyncio.run(ofix.add_lines(None, "order-a", [_add(INVOICE_PRICE_A, bump=False)], "n"))
        self.assertEqual([e for e in self.store.log if e[0] == "set"], [])


if __name__ == "__main__":
    unittest.main()
