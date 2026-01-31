-- Migration: Add Item Tracker Configuration Table
-- Version: 001
-- Date: 2026-01-30
-- Description: Adds item_tracker_config table for Item Tracker feature

-- Check if table already exists before creating
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'item_tracker_config') THEN
        -- Item Tracker configuration (singleton pattern)
        CREATE TABLE item_tracker_config (
            id SERIAL PRIMARY KEY,
            s2s_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            sales_store_ids JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Only one config row allowed
        CREATE UNIQUE INDEX idx_item_tracker_singleton ON item_tracker_config ((true));

        -- Trigger for auto-updating updated_at
        CREATE TRIGGER update_item_tracker_config_updated_at
            BEFORE UPDATE ON item_tracker_config
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

        RAISE NOTICE 'Created item_tracker_config table';
    ELSE
        RAISE NOTICE 'Table item_tracker_config already exists, skipping';
    END IF;
END $$;
