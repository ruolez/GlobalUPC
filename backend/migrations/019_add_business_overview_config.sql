-- Migration: Business Overview dashboard configuration
-- Version: 019
-- Date: 2026-08-17
-- Description: Singleton config for the Business Overview page: which MSSQL
--              store is the sales/invoices source, which is the purchases
--              source, which Shopify stores to include, which DB_ADMIN
--              quotation statuses count as "in progress", and the timezone
--              used to resolve "today"/"this week" server-side.
--              DB_ADMIN itself still comes from settings.admin_store_id.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'business_overview_config') THEN
        CREATE TABLE business_overview_config (
            id SERIAL PRIMARY KEY,
            sales_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            purchases_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            shopify_store_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            quotation_statuses JSONB NOT NULL DEFAULT '["In Progress","Locked"]'::jsonb,
            timezone VARCHAR(64) NOT NULL DEFAULT 'America/Chicago',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Only one config row allowed
        CREATE UNIQUE INDEX idx_business_overview_config_singleton
            ON business_overview_config ((true));

        CREATE TRIGGER update_business_overview_config_updated_at
            BEFORE UPDATE ON business_overview_config
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

        RAISE NOTICE 'Created business_overview_config table';
    ELSE
        RAISE NOTICE 'Table business_overview_config already exists, skipping';
    END IF;
END $$;
