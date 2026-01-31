-- Migration: Add Item Tracker Exclusions Table
-- Version: 002
-- Date: 2026-01-30
-- Description: Adds item_tracker_exclusions table for excluding customers/suppliers from Item Tracker results

-- Check if table already exists before creating
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'item_tracker_exclusions') THEN
        -- Item Tracker exclusions table
        CREATE TABLE item_tracker_exclusions (
            id SERIAL PRIMARY KEY,
            business_name VARCHAR(255) NOT NULL UNIQUE,
            excluded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        );

        -- Index for fast lookups by business name
        CREATE INDEX idx_item_tracker_exclusions_name ON item_tracker_exclusions(business_name);

        RAISE NOTICE 'Created item_tracker_exclusions table';
    ELSE
        RAISE NOTICE 'Table item_tracker_exclusions already exists, skipping';
    END IF;
END $$;
