-- Migration: Add inventory_store_id to Item Tracker Config
-- Version: 004
-- Date: 2026-02-03
-- Description: Adds inventory_store_id column for inventory recount database

DO $$
BEGIN
    -- Add inventory_store_id column if it doesn't exist
    IF NOT EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_name = 'item_tracker_config'
        AND column_name = 'inventory_store_id'
    ) THEN
        ALTER TABLE item_tracker_config
        ADD COLUMN inventory_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL;

        RAISE NOTICE 'Added inventory_store_id column to item_tracker_config';
    ELSE
        RAISE NOTICE 'Column inventory_store_id already exists, skipping';
    END IF;
END $$;
