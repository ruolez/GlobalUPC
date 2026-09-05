-- Migration: Order Sync fix history
-- Version: 028
-- Date: 2026-09-05
-- Description: Audit log for "Fix in Shopify" runs from the Order Sync page —
--              one row per Shopify order touched, with the planned actions,
--              the executed steps (refund / order edit / fulfillment / mark
--              paid / tracking, with the Shopify ids they created) and the
--              row status before and after.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'order_sync_fix_history') THEN
        CREATE TABLE order_sync_fix_history (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(36) NOT NULL,
            shopify_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            store_name VARCHAR(255),
            sh_order_id VARCHAR(64) NOT NULL,
            sh_order_name VARCHAR(64),
            bo_invoice_id INTEGER,
            bo_invoice_number VARCHAR(64),
            status VARCHAR(16) NOT NULL,
            status_before VARCHAR(32),
            status_after VARCHAR(32),
            actions JSONB,
            steps JSONB,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX idx_order_sync_fix_history_batch ON order_sync_fix_history (batch_id);
        CREATE INDEX idx_order_sync_fix_history_order ON order_sync_fix_history (sh_order_id);
        CREATE INDEX idx_order_sync_fix_history_created ON order_sync_fix_history (created_at);

        RAISE NOTICE 'Created order_sync_fix_history table';
    ELSE
        RAISE NOTICE 'Table order_sync_fix_history already exists, skipping';
    END IF;
END $$;
