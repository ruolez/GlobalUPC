-- Migration: Business Overview — purchase-order product exclusions
-- Version: 024
-- Date: 2026-08-21
-- Description: Products (by BackOffice ProductID, scoped to the configured
--              purchases store) excluded from Overview purchase-order
--              quantity/outstanding calculations — e.g. shipping charges or
--              discounts that are not real merchandise. PoTotal is untouched.

CREATE TABLE IF NOT EXISTS business_overview_po_product_exclusions (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,  -- purchases store
    product_id INTEGER NOT NULL,      -- PurchaseOrdersDetails_tbl.ProductID
    product_sku TEXT,
    product_upc TEXT,
    description TEXT,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bov_po_excl_unique
    ON business_overview_po_product_exclusions (store_id, product_id);
