-- Migration: Order Sync created products
-- Version: 030
-- Date: 2026-09-22
-- Description: Audit log of every Shopify product "Fix in Shopify" created for
--              a BackOffice UPC that the store did not carry. One row per
--              product actually created (a product that already existed and
--              was reused is not logged). Backs the "Created products" view on
--              the Order Sync page, so a catalog change made by this app is
--              never invisible.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'order_sync_created_products') THEN
        CREATE TABLE order_sync_created_products (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(36),
            shopify_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
            store_name VARCHAR(255),
            barcode VARCHAR(64) NOT NULL,
            title VARCHAR(255),
            sku VARCHAR(64),
            price NUMERIC(14, 2),
            unit_cost NUMERIC(14, 2),
            price_source VARCHAR(16),          -- items_tbl | invoice
            product_gid VARCHAR(64) NOT NULL,
            variant_gid VARCHAR(64),
            sh_order_id VARCHAR(64),
            sh_order_name VARCHAR(64),
            bo_invoice_id INTEGER,
            bo_invoice_number VARCHAR(64),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX idx_order_sync_created_products_created ON order_sync_created_products (created_at DESC);
        CREATE INDEX idx_order_sync_created_products_barcode ON order_sync_created_products (barcode);
        CREATE INDEX idx_order_sync_created_products_store ON order_sync_created_products (shopify_store_id);

        RAISE NOTICE 'Created order_sync_created_products table';
    ELSE
        RAISE NOTICE 'Table order_sync_created_products already exists, skipping';
    END IF;
END $$;
