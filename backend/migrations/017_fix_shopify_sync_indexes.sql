-- Migration: Fix Shopify sync indexes for the local report queries
-- Version: 017
-- Date: 2026-08-01
-- Description: Two audit findings, both verified with EXPLAIN against real
--              data. (1) idx_shopcust_namezip did not match the expression the
--              cross-store name probe actually filters on, so the probe was a
--              sequential scan; replaced with an expression index on the exact
--              normalized name key. (2) The first-orders aggregation filters
--              on (store_id, customer_shopify_id) over ALL orders (the
--              lifetime count needs cancelled ones too), which the partial
--              completed-orders index cannot serve; add a plain index.

DROP INDEX IF EXISTS idx_shopcust_namezip;

-- Must stay textually equivalent to _NAME_KEY_SQL in lost_customers_local.py:
-- lower -> collapse runs of whitespace -> trim, then first|last.
CREATE INDEX IF NOT EXISTS idx_shopcust_namekey ON shopify_customers (
    ((btrim(regexp_replace(lower(coalesce(first_name, '')), '\s+', ' ', 'g')) || '|' ||
      btrim(regexp_replace(lower(coalesce(last_name, '')), '\s+', ' ', 'g'))))
);

CREATE INDEX IF NOT EXISTS idx_shoporder_customer
    ON shopify_orders(store_id, customer_shopify_id);
