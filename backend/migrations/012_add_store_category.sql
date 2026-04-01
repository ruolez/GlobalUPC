-- Migration: Add store_category to stores
-- Version: 012
-- Date: 2026-04-01
-- Description: Adds wholesale/retail category enum to stores table

-- Create ENUM type if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'store_category') THEN
        CREATE TYPE store_category AS ENUM ('wholesale', 'retail');
        RAISE NOTICE 'Created store_category enum type';
    ELSE
        RAISE NOTICE 'store_category enum type already exists, skipping';
    END IF;
END $$;

-- Add column if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_name = 'stores'
        AND column_name = 'store_category'
    ) THEN
        ALTER TABLE stores
        ADD COLUMN store_category store_category NOT NULL DEFAULT 'retail';

        RAISE NOTICE 'Added store_category column to stores';
    ELSE
        RAISE NOTICE 'Column store_category already exists, skipping';
    END IF;
END $$;
