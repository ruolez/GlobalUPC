-- Migration: Fields needed to run the Shopify Sales report from the local mirror
-- Version: 018
-- Date: 2026-08-17
-- Description: current_quantity (post-refund/edit quantity) on line items and
--              total_shipping on orders. Per-fulfillment `status` is captured
--              inside the existing fulfillments JSONB (no DDL needed).
--              NULL in either column means the row has not been re-synced since
--              this migration; the local report falls back to quantity / 0
--              shipping / displayStatus. A Full resync backfills everything.

ALTER TABLE shopify_order_line_items ADD COLUMN IF NOT EXISTS current_quantity INTEGER;
ALTER TABLE shopify_orders ADD COLUMN IF NOT EXISTS total_shipping NUMERIC(14,2);
