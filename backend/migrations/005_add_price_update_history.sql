-- Migration: Add price_update_history table
-- Version: 005
-- Date: 2026-02-13
-- Description: Adds price_update_history table for tracking price/cost changes

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_name = 'price_update_history'
    ) THEN
        CREATE TABLE price_update_history (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(36) NOT NULL,
            store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            store_name VARCHAR(255) NOT NULL,
            store_type store_type NOT NULL,
            upc VARCHAR(255) NOT NULL,
            product_description TEXT,
            variant_id VARCHAR(255),
            variant_title VARCHAR(255),
            old_price NUMERIC(10,2),
            old_cost NUMERIC(10,2),
            new_price NUMERIC(10,2),
            new_cost NUMERIC(10,2),
            success BOOLEAN NOT NULL,
            rows_affected INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX idx_price_history_batch_id ON price_update_history(batch_id);
        CREATE INDEX idx_price_history_store_id ON price_update_history(store_id);
        CREATE INDEX idx_price_history_created_at ON price_update_history(created_at DESC);
        CREATE INDEX idx_price_history_upc ON price_update_history(upc);

        RAISE NOTICE 'Created price_update_history table with indexes';
    ELSE
        RAISE NOTICE 'Table price_update_history already exists, skipping';
    END IF;
END $$;
