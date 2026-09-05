-- Migration: Shopify mirror — after-returns order totals
-- Version: 029
-- Date: 2026-09-05
-- Description: Adds Shopify's currentSubtotalPrice / currentTotalPrice to the
--              local order mirror. A records-only ($0) line refund — what the
--              Order Sync "Fix in Shopify" does to remove or reprice a shipped
--              line — lowers the current totals but leaves subtotal_price and
--              total_refunded untouched, so order-level revenue must be read
--              as LEAST(subtotal_price, current_subtotal_price + total_refunded).
--              Rows synced before this migration keep NULL until the next
--              incremental sync touches them (COALESCE falls back to subtotal).

ALTER TABLE shopify_orders ADD COLUMN IF NOT EXISTS current_subtotal_price NUMERIC(14,2);
ALTER TABLE shopify_orders ADD COLUMN IF NOT EXISTS current_total_price NUMERIC(14,2);
