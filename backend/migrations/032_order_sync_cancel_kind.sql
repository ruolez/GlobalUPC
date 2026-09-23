-- Migration: Order Sync cancel kinds
-- Version: 032
-- Date: 2026-09-23
-- Description: order_sync_cancelled_orders now also logs the "Online Store"
--              pass, which cancels every Online Store order that is not
--              UNFULFILLED (its real copy came in through the web-hook
--              channel). `kind` tells the two passes apart; the web-hook copy,
--              when found, is stored in twin_order_* like a duplicate's
--              survivor, so the Duplicates pass never targets it later.

ALTER TABLE order_sync_cancelled_orders ADD COLUMN IF NOT EXISTS kind VARCHAR(16) DEFAULT 'duplicate';
ALTER TABLE order_sync_cancelled_orders ADD COLUMN IF NOT EXISTS channel VARCHAR(64);
ALTER TABLE order_sync_cancelled_orders ADD COLUMN IF NOT EXISTS fulfillment_status VARCHAR(30);
ALTER TABLE order_sync_cancelled_orders ADD COLUMN IF NOT EXISTS fulfillments_cancelled INTEGER DEFAULT 0;
