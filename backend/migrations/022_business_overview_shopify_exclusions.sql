-- Migration: Business Overview — Shopify product exclusions
-- Version: 022
-- Date: 2026-08-18
-- Description: Products (by barcode or Shopify variant id, optionally per store)
--              excluded from Overview Shopify revenue/cost/unit figures, top
--              products and the "products without cost" report — e.g. shipping
--              protection or fees that are not real merchandise.

CREATE TABLE IF NOT EXISTS business_overview_shopify_exclusions (
    id SERIAL PRIMARY KEY,
    store_id INTEGER REFERENCES stores(id) ON DELETE CASCADE,   -- NULL = every store
    variant_shopify_id BIGINT,
    product_shopify_id BIGINT,
    barcode TEXT,
    sku TEXT,
    title TEXT,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bov_shopify_excl_unique
    ON business_overview_shopify_exclusions (COALESCE(store_id, 0), COALESCE(variant_shopify_id, 0), COALESCE(product_shopify_id, 0), COALESCE(barcode, ''));
