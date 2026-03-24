-- Migration: Add excluded_subcategories to sales_config
-- Version: 011
-- Date: 2026-03-23

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'sales_config' AND column_name = 'excluded_subcategories'
    ) THEN
        ALTER TABLE sales_config ADD COLUMN excluded_subcategories JSONB DEFAULT '[]'::jsonb;
        RAISE NOTICE 'Added excluded_subcategories column to sales_config';
    ELSE
        RAISE NOTICE 'Column excluded_subcategories already exists, skipping';
    END IF;
END $$;
