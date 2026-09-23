-- Migration: Order Sync cancelled duplicate orders
-- Version: 031
-- Date: 2026-09-22
-- Description: Audit log of every Shopify order the Order Sync "Duplicates"
--              pass cancelled, or tried to. One row per attempt, written as
--              `pending` before the mutation and updated after: cancelling an
--              order is irreversible, so an attempt that dies mid-flight must
--              still be visible. `twin_order_id` also protects the surviving
--              order from being offered as a cancel target on a later run.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'order_sync_cancelled_orders') THEN
        CREATE TABLE order_sync_cancelled_orders (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(36),
            shopify_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            store_name VARCHAR(255),
            sh_order_id VARCHAR(64) NOT NULL,
            sh_order_name VARCHAR(64),
            sh_order_total NUMERIC(14, 2),
            sh_order_date VARCHAR(10),
            customer_gid VARCHAR(64),
            twin_order_id VARCHAR(64),
            twin_order_name VARCHAR(64),
            twin_order_total NUMERIC(14, 2),
            twin_order_date VARCHAR(10),
            twin_tier INTEGER,                 -- 0 invoice | 1 tracking | 2 neither
            total_delta NUMERIC(14, 2),
            total_delta_pct NUMERIC(6, 2),
            date_delta_days INTEGER,
            cluster_size INTEGER,
            ambiguous BOOLEAN DEFAULT FALSE,
            flags JSONB,
            alternatives JSONB,
            staff_note TEXT,
            financial_status VARCHAR(30),
            net_payment NUMERIC(14, 2),
            status VARCHAR(16) NOT NULL,       -- pending | cancelled | noop | skipped | failed
            cancel_job_id VARCHAR(128),
            verified_cancelled BOOLEAN DEFAULT FALSE,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX idx_order_sync_cancelled_created ON order_sync_cancelled_orders (created_at DESC);
        CREATE INDEX idx_order_sync_cancelled_order ON order_sync_cancelled_orders (sh_order_id);
        CREATE INDEX idx_order_sync_cancelled_twin ON order_sync_cancelled_orders (twin_order_id);
        CREATE INDEX idx_order_sync_cancelled_store ON order_sync_cancelled_orders (shopify_store_id);

        RAISE NOTICE 'Created order_sync_cancelled_orders table';
    ELSE
        RAISE NOTICE 'Table order_sync_cancelled_orders already exists, skipping';
    END IF;
END $$;
