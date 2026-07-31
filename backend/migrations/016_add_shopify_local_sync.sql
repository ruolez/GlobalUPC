-- Migration: Add Shopify local data sync tables
-- Version: 016
-- Date: 2026-07-31
-- Description: Per-store local mirror of Shopify customers and orders (with line
--              items and fulfillments) so reports like Lost Customers can run
--              from PostgreSQL instead of live Shopify GraphQL. The sync-state
--              row per store also acts as the cross-worker concurrency guard.

-- Sync state: one row per store; claimed via conditional UPDATE (status/heartbeat)
CREATE TABLE IF NOT EXISTS shopify_sync_state (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL UNIQUE REFERENCES stores(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    phase VARCHAR(40),
    mode VARCHAR(12),
    run_started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    last_completed_at TIMESTAMPTZ,
    last_sync_started_at TIMESTAMPTZ,
    shop_timezone VARCHAR(64),
    customers_count INTEGER DEFAULT 0,
    orders_count INTEGER DEFAULT 0,
    line_items_count INTEGER DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_shopify_sync_state_updated_at') THEN
        CREATE TRIGGER update_shopify_sync_state_updated_at BEFORE UPDATE ON shopify_sync_state
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- Customers: real columns for report filters/joins, full payload kept in raw
CREATE TABLE IF NOT EXISTS shopify_customers (
    id BIGSERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    shopify_id BIGINT NOT NULL,
    shopify_gid TEXT NOT NULL,
    email TEXT,
    email_normalized TEXT,
    first_name TEXT,
    last_name TEXT,
    display_name TEXT,
    phone TEXT,
    state VARCHAR(30),
    verified_email BOOLEAN,
    tags TEXT[],
    note TEXT,
    number_of_orders INTEGER,
    amount_spent NUMERIC(14,2),
    currency VARCHAR(10),
    default_address_zip TEXT,
    default_province_code TEXT,
    default_country_code TEXT,
    created_at TIMESTAMPTZ,
    shopify_updated_at TIMESTAMPTZ,
    raw JSONB NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, shopify_id)
);

CREATE INDEX IF NOT EXISTS idx_shopcust_store_created ON shopify_customers(store_id, created_at);
CREATE INDEX IF NOT EXISTS idx_shopcust_email ON shopify_customers(email_normalized);
CREATE INDEX IF NOT EXISTS idx_shopcust_namezip ON shopify_customers(lower(last_name), lower(first_name), default_address_zip);
CREATE INDEX IF NOT EXISTS idx_shopcust_synced ON shopify_customers(store_id, synced_at);

-- Orders: first-fulfillment fields promoted to columns, full timeline in fulfillments JSONB
CREATE TABLE IF NOT EXISTS shopify_orders (
    id BIGSERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    shopify_id BIGINT NOT NULL,
    shopify_gid TEXT NOT NULL,
    name TEXT,
    customer_shopify_id BIGINT,
    email TEXT,
    created_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    shopify_updated_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    financial_status VARCHAR(30),
    fulfillment_status VARCHAR(30),
    tags TEXT[],
    note TEXT,
    total_price NUMERIC(14,2),
    subtotal_price NUMERIC(14,2),
    total_discounts NUMERIC(14,2),
    total_refunded NUMERIC(14,2),
    currency VARCHAR(10),
    ship_province_code TEXT,
    ship_province TEXT,
    ship_country_code TEXT,
    ship_zip TEXT,
    ship_city TEXT,
    shipping_line_title TEXT,
    shipping_carrier_identifier TEXT,
    fulfilled_at TIMESTAMPTZ,
    in_transit_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    tracking_company TEXT,
    tracking_number TEXT,
    tracking_url TEXT,
    fulfillments JSONB,
    raw JSONB NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, shopify_id)
);

-- Partial index matching the completed-order rule: -status:cancelled -financial_status:refunded
CREATE INDEX IF NOT EXISTS idx_shoporder_completed
    ON shopify_orders(store_id, customer_shopify_id, created_at)
    WHERE cancelled_at IS NULL AND financial_status IS DISTINCT FROM 'REFUNDED';
CREATE INDEX IF NOT EXISTS idx_shoporder_store_created ON shopify_orders(store_id, created_at);
CREATE INDEX IF NOT EXISTS idx_shoporder_synced ON shopify_orders(store_id, synced_at);

-- Line items: composite FK to the order's natural key so pruning/store deletion cascade
CREATE TABLE IF NOT EXISTS shopify_order_line_items (
    id BIGSERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    order_shopify_id BIGINT NOT NULL,
    shopify_id BIGINT NOT NULL,
    title TEXT,
    variant_title TEXT,
    sku TEXT,
    vendor TEXT,
    barcode TEXT,
    product_title TEXT,
    product_shopify_id BIGINT,
    variant_shopify_id BIGINT,
    quantity INTEGER,
    original_unit_price NUMERIC(14,2),
    discounted_total NUMERIC(14,2),
    raw JSONB,
    UNIQUE (store_id, shopify_id),
    FOREIGN KEY (store_id, order_shopify_id)
        REFERENCES shopify_orders(store_id, shopify_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sholi_order ON shopify_order_line_items(store_id, order_shopify_id);
