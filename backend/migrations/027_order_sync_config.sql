-- Migration: Order Sync configuration
-- Version: 027
-- Date: 2026-09-04
-- Description: Singleton config for the Order Sync page: which BackOffice
--              MSSQL store and which Shopify store to reconcile shipped
--              orders between (tracking-number + customer-identity matching,
--              line-level product/qty/price comparison).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'order_sync_config') THEN
        CREATE TABLE order_sync_config (
            id SERIAL PRIMARY KEY,
            mssql_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            shopify_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Only one config row allowed
        CREATE UNIQUE INDEX idx_order_sync_config_singleton
            ON order_sync_config ((true));

        CREATE TRIGGER update_order_sync_config_updated_at
            BEFORE UPDATE ON order_sync_config
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

        RAISE NOTICE 'Created order_sync_config table';
    ELSE
        RAISE NOTICE 'Table order_sync_config already exists, skipping';
    END IF;
END $$;
