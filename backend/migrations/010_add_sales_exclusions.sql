-- Migration: Add Sales Exclusions Table
-- Version: 010
-- Date: 2026-03-23

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'sales_exclusions') THEN
        CREATE TABLE sales_exclusions (
            id SERIAL PRIMARY KEY,
            business_name VARCHAR(255) NOT NULL,
            void_status INTEGER,
            excluded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        );

        CREATE INDEX idx_sales_exclusions_name ON sales_exclusions(business_name);

        RAISE NOTICE 'Created sales_exclusions table';
    ELSE
        RAISE NOTICE 'Table sales_exclusions already exists, skipping';
    END IF;
END $$;
