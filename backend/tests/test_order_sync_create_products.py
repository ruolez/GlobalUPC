"""
Product creation for a UPC the Shopify store does not carry
(order_sync_fix_helper.create_missing_products) — no database, no network:
the GraphQL call and the catalog lookup are stubbed.

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

BARCODE = "086400901826"
PRODUCT = "gid://shopify/Product/10495555240252"
VARIANT = "gid://shopify/ProductVariant/54443167777084"


def _action(barcode=BARCODE, price=23.75, cost=21.0, sku="pJobVirgin"):
    return {"kind": "create_product", "reason": "create", "key": barcode, "barcode": barcode,
            "title": "Job Virgin  1 1/4", "description": "Job Virgin  1 1/4", "sku": sku,
            "unit_price": price, "unit_cost": cost, "price_source": "items_tbl"}


class FakeShopify:
    """A catalog that starts empty, records every productSet input, and hands
    back what Shopify would return."""

    def __init__(self, existing=None):
        self.catalog = dict(existing or {})
        self.inputs = []
        self.lookups = 0

    async def find(self, session, shop, key, version, barcodes):
        self.lookups += 1
        return {b: self.catalog[b] for b in barcodes if b in self.catalog}

    async def gql(self, ctx, query, variables):
        inp = variables["input"]
        self.inputs.append(inp)
        v = inp["variants"][0]
        self.catalog[v["barcode"]] = {"variant_id": VARIANT, "product_id": PRODUCT,
                                      "price": float(v["price"]), "price_raw": v["price"],
                                      "product_title": inp["title"]}
        return {"productSet": {"product": {
            "id": PRODUCT, "status": inp["status"],
            "variants": {"nodes": [{"id": VARIANT, "price": v["price"],
                                    "barcode": v["barcode"], "sku": v.get("sku", "")}]},
        }, "userErrors": []}}


class CreateMissingProductsTests(unittest.TestCase):
    def setUp(self):
        self.shop = FakeShopify()
        self._orig = (ofix._gql, ofix.find_variants_by_barcode)
        ofix._gql = self.shop.gql
        ofix.find_variants_by_barcode = self.shop.find
        self.ctx = ofix.ShopifyCtx(None, "shop.myshopify.com", "key", "2025-01")

    def tearDown(self):
        ofix._gql, ofix.find_variants_by_barcode = self._orig

    def test_product_is_created_hidden_untracked_and_carries_the_upc(self):
        made = asyncio.run(ofix.create_missing_products(self.ctx, [_action()]))
        self.assertEqual(made[BARCODE]["variant_id"], VARIANT)
        self.assertEqual(made[BARCODE]["product_id"], PRODUCT)
        self.assertEqual(made[BARCODE]["price"], 23.75)
        self.assertNotIn("reused", made[BARCODE])

        sent = self.shop.inputs[0]
        self.assertEqual(sent["status"], "ACTIVE")
        self.assertEqual(sent["tags"], [ofix.PRODUCT_BACKFILL_TAG])
        self.assertEqual(sent["title"], "Job Virgin  1 1/4")
        variant = sent["variants"][0]
        self.assertEqual(variant["barcode"], BARCODE)
        self.assertEqual(variant["sku"], "pJobVirgin")
        self.assertEqual(variant["price"], "23.75")
        self.assertEqual(variant["inventoryPolicy"], "CONTINUE")
        self.assertEqual(variant["inventoryItem"], {"tracked": False, "cost": "21.00"})
        # Nothing publishes the product, so it lands on no sales channel.
        self.assertNotIn("productPublications", sent)

    def test_zero_cost_is_left_off_the_inventory_item(self):
        asyncio.run(ofix.create_missing_products(self.ctx, [_action(cost=0)]))
        self.assertEqual(self.shop.inputs[0]["variants"][0]["inventoryItem"], {"tracked": False})

    def test_a_barcode_already_in_the_catalog_is_reused_not_created(self):
        self.shop.catalog[BARCODE] = {"variant_id": "gid://shopify/ProductVariant/9",
                                      "product_id": "gid://shopify/Product/9",
                                      "price": 19.0, "price_raw": "19.00", "product_title": "Already there"}
        made = asyncio.run(ofix.create_missing_products(self.ctx, [_action()]))
        self.assertTrue(made[BARCODE]["reused"])
        self.assertEqual(made[BARCODE]["variant_id"], "gid://shopify/ProductVariant/9")
        self.assertEqual(self.shop.inputs, [])

    def test_two_orders_needing_the_same_upc_create_it_once(self):
        # The catalog is re-checked inside the lock, so the second caller
        # finds what the first one just made.
        async def run():
            return await asyncio.gather(
                ofix.create_missing_products(self.ctx, [_action()]),
                ofix.create_missing_products(self.ctx, [_action()]),
            )
        a, b = asyncio.run(run())
        self.assertEqual(len(self.shop.inputs), 1)
        self.assertEqual(a[BARCODE]["variant_id"], b[BARCODE]["variant_id"])
        self.assertTrue(a[BARCODE].get("reused") or b[BARCODE].get("reused"))

    def test_a_variant_coming_back_with_the_wrong_barcode_fails_loudly(self):
        async def wrong(ctx, query, variables):
            return {"productSet": {"product": {
                "id": PRODUCT, "status": "ACTIVE",
                "variants": {"nodes": [{"id": VARIANT, "price": "23.75", "barcode": "999", "sku": ""}]},
            }, "userErrors": []}}
        ofix._gql = wrong
        with self.assertRaises(ofix.FixStepError) as cm:
            asyncio.run(ofix.create_missing_products(self.ctx, [_action()]))
        self.assertEqual(cm.exception.step, "create_product")

    def test_shopify_user_errors_surface_as_a_create_product_failure(self):
        async def rejected(ctx, query, variables):
            return {"productSet": {"product": None,
                                   "userErrors": [{"field": ["variants", "barcode"], "message": "is invalid"}]}}
        ofix._gql = rejected
        with self.assertRaises(ofix.FixStepError) as cm:
            asyncio.run(ofix.create_missing_products(self.ctx, [_action()]))
        self.assertEqual(cm.exception.step, "create_product")
        self.assertIn("is invalid", cm.exception.message)


class ProductStatusTests(unittest.TestCase):
    """The live re-check behind the created-products log."""

    def setUp(self):
        self._orig = ofix._gql
        self.ctx = ofix.ShopifyCtx(None, "shop.myshopify.com", "key", "2025-01")

    def tearDown(self):
        ofix._gql = self._orig

    def _run(self, nodes):
        async def gql(ctx, query, variables):
            return {"nodes": nodes}
        ofix._gql = gql
        return asyncio.run(ofix.fetch_product_status(self.ctx, [PRODUCT]))

    def test_hidden_product_reports_unpublished(self):
        got = self._run([{"id": PRODUCT, "title": "T", "status": "ACTIVE",
                          "publishedAt": None, "onlineStoreUrl": None,
                          "variants": {"nodes": [{"barcode": BARCODE, "sku": "s", "price": "23.75"}]}}])
        self.assertEqual(got[PRODUCT]["status"], "ACTIVE")
        self.assertFalse(got[PRODUCT]["published"])
        self.assertEqual(got[PRODUCT]["barcode"], BARCODE)

    def test_a_published_product_is_flagged(self):
        got = self._run([{"id": PRODUCT, "title": "T", "status": "ACTIVE",
                          "publishedAt": "2026-09-22T00:00:00Z", "onlineStoreUrl": None,
                          "variants": {"nodes": []}}])
        self.assertTrue(got[PRODUCT]["published"])

    def test_a_deleted_product_is_absent_from_the_result(self):
        self.assertEqual(self._run([None]), {})


if __name__ == "__main__":
    unittest.main()
