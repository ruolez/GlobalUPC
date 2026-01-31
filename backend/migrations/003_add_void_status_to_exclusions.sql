-- Migration: Add void_status column to Item Tracker Exclusions
-- Version: 003
-- Date: 2026-01-31
-- Description: Adds void_status column for void-aware exclusion filtering
--   NULL = exclude all events (current behavior)
--   0 = exclude non-voided invoices only
--   1 = exclude voided invoices only

DO $$
BEGIN
    -- Add void_status column if it doesn't exist
    IF NOT EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_name = 'item_tracker_exclusions'
        AND column_name = 'void_status'
    ) THEN
        -- Add nullable void_status column
        ALTER TABLE item_tracker_exclusions ADD COLUMN void_status INTEGER;

        -- Drop old unique constraint on business_name only
        ALTER TABLE item_tracker_exclusions DROP CONSTRAINT IF EXISTS item_tracker_exclusions_business_name_key;

        -- Add new unique index on (business_name, void_status)
        -- Use COALESCE to handle NULL in uniqueness (-1 represents NULL)
        CREATE UNIQUE INDEX idx_exclusions_name_void
            ON item_tracker_exclusions(business_name, COALESCE(void_status, -1));

        RAISE NOTICE 'Added void_status column to item_tracker_exclusions';
    ELSE
        RAISE NOTICE 'Column void_status already exists, skipping';
    END IF;
END $$;
