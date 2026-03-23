-- Migration: Add Sales Report Configuration Table
-- Version: 009
-- Date: 2026-03-23
-- Description: Adds sales_config table for Sales Report feature

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'sales_config') THEN
        CREATE TABLE sales_config (
            id SERIAL PRIMARY KEY,
            s2s_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            mssql_store_ids JSONB DEFAULT '[]'::jsonb,
            shopify_store_ids JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Only one config row allowed
        CREATE UNIQUE INDEX idx_sales_config_singleton ON sales_config ((true));

        -- Trigger for auto-updating updated_at
        CREATE TRIGGER update_sales_config_updated_at
            BEFORE UPDATE ON sales_config
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

        RAISE NOTICE 'Created sales_config table';
    ELSE
        RAISE NOTICE 'Table sales_config already exists, skipping';
    END IF;
END $$;
