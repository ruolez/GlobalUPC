-- Migration: Add 'shipper' to store_type enum
-- Version: 015
-- Date: 2026-06-23
-- Description: Adds 'shipper' as a third store_type for shipping-platform MSSQL databases

-- ALTER TYPE ... ADD VALUE is not idempotent on its own, so guard it
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'store_type' AND e.enumlabel = 'shipper'
    ) THEN
        ALTER TYPE store_type ADD VALUE 'shipper';
        RAISE NOTICE 'Added shipper to store_type enum';
    ELSE
        RAISE NOTICE 'shipper already in store_type enum, skipping';
    END IF;
END $$;
