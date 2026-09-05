-- Global UPC Database Schema

-- Store types enum
CREATE TYPE store_type AS ENUM ('mssql', 'shopify', 'shipper');

-- Store category enum
CREATE TYPE store_category AS ENUM ('wholesale', 'retail');

-- Stores table - holds all configured database and Shopify store connections
CREATE TABLE stores (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    store_type store_type NOT NULL,
    store_category store_category NOT NULL DEFAULT 'retail',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- MSSQL database connections
CREATE TABLE mssql_connections (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    host VARCHAR(255) NOT NULL,
    port INTEGER DEFAULT 1433,
    database_name VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id)
);

-- Shopify store connections (Admin API token or OAuth client credentials).
-- admin_api_key holds the current access token in both modes: the permanent
-- shpat_ token (auth_method = 'token') or the cached 24h OAuth token
-- (auth_method = 'client_credentials', refreshed by the backend).
CREATE TABLE shopify_connections (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    shop_domain VARCHAR(255) NOT NULL,
    admin_api_key VARCHAR(512),
    auth_method VARCHAR(30) NOT NULL DEFAULT 'token',
    client_id VARCHAR(255),
    client_secret VARCHAR(255),
    token_expires_at TIMESTAMPTZ,
    api_version VARCHAR(50) DEFAULT '2025-01',
    update_sku_with_barcode BOOLEAN DEFAULT false,
    first_order_tag VARCHAR(100) NOT NULL DEFAULT 'First order',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id),
    UNIQUE(shop_domain)
);

-- Application settings
CREATE TABLE settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_stores_type ON stores(store_type);
CREATE INDEX idx_stores_active ON stores(is_active);
CREATE INDEX idx_settings_key ON settings(key);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers to auto-update updated_at
CREATE TRIGGER update_stores_updated_at BEFORE UPDATE ON stores
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_mssql_connections_updated_at BEFORE UPDATE ON mssql_connections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_shopify_connections_updated_at BEFORE UPDATE ON shopify_connections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_settings_updated_at BEFORE UPDATE ON settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- UPC update history tracking
CREATE TABLE upc_update_history (
    id SERIAL PRIMARY KEY,
    batch_id VARCHAR(36) NOT NULL,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    store_name VARCHAR(255) NOT NULL,
    store_type store_type NOT NULL,
    old_upc VARCHAR(255) NOT NULL,
    new_upc VARCHAR(255) NOT NULL,

    -- Context fields (nullable for flexibility)
    product_id VARCHAR(255),
    product_title TEXT,
    variant_id VARCHAR(255),
    variant_title VARCHAR(255),
    table_name VARCHAR(255),
    primary_keys JSONB,

    -- Result fields
    success BOOLEAN NOT NULL,
    items_updated_count INTEGER DEFAULT 0,
    error_message TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for history queries
CREATE INDEX idx_history_batch_id ON upc_update_history(batch_id);
CREATE INDEX idx_history_store_id ON upc_update_history(store_id);
CREATE INDEX idx_history_created_at ON upc_update_history(created_at DESC);
CREATE INDEX idx_history_old_upc ON upc_update_history(old_upc);
CREATE INDEX idx_history_new_upc ON upc_update_history(new_upc);

-- UPC exclusions for orphaned UPC audits
CREATE TABLE upc_exclusions (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    upc VARCHAR(255) NOT NULL,
    excluded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    UNIQUE(store_id, upc)
);

-- Index for fast exclusion lookups during audits
CREATE INDEX idx_exclusions_store_upc ON upc_exclusions(store_id, upc);
CREATE INDEX idx_exclusions_store_id ON upc_exclusions(store_id);

-- Item Tracker configuration (singleton pattern)
CREATE TABLE item_tracker_config (
    id SERIAL PRIMARY KEY,
    s2s_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    sales_store_ids JSONB DEFAULT '[]'::jsonb,
    inventory_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Only one config row allowed
CREATE UNIQUE INDEX idx_item_tracker_singleton ON item_tracker_config ((true));

CREATE TRIGGER update_item_tracker_config_updated_at
    BEFORE UPDATE ON item_tracker_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Item Tracker exclusions for customers/suppliers
CREATE TABLE item_tracker_exclusions (
    id SERIAL PRIMARY KEY,
    business_name VARCHAR(255) NOT NULL,
    void_status INTEGER,  -- NULL=all events, 0=non-voided only, 1=voided only
    excluded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Index for fast lookups by business name
CREATE INDEX idx_item_tracker_exclusions_name ON item_tracker_exclusions(business_name);
-- Unique constraint on (business_name, void_status) using COALESCE for NULL handling
CREATE UNIQUE INDEX idx_exclusions_name_void
    ON item_tracker_exclusions(business_name, COALESCE(void_status, -1));

-- Price update history tracking
CREATE TABLE price_update_history (
    id SERIAL PRIMARY KEY,
    batch_id VARCHAR(36) NOT NULL,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    store_name VARCHAR(255) NOT NULL,
    store_type store_type NOT NULL,
    upc VARCHAR(255) NOT NULL,
    product_description TEXT,
    variant_id VARCHAR(255),
    variant_title VARCHAR(255),
    variant_barcode VARCHAR(255),
    old_price NUMERIC(10,2),
    old_cost NUMERIC(10,2),
    new_price NUMERIC(10,2),
    new_cost NUMERIC(10,2),
    old_delivery_b NUMERIC(10,2),
    new_delivery_b NUMERIC(10,2),
    old_list_price NUMERIC(10,2),
    new_list_price NUMERIC(10,2),
    success BOOLEAN NOT NULL,
    rows_affected INTEGER DEFAULT 0,
    error_message TEXT,
    is_mirror BOOLEAN DEFAULT false,
    mirror_source_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_price_history_batch_id ON price_update_history(batch_id);
CREATE INDEX idx_price_history_store_id ON price_update_history(store_id);
CREATE INDEX idx_price_history_created_at ON price_update_history(created_at DESC);
CREATE INDEX idx_price_history_upc ON price_update_history(upc);

-- Store mirrors for price update propagation
CREATE TABLE store_mirrors (
    id SERIAL PRIMARY KEY,
    source_store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    mirror_store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_store_id, mirror_store_id),
    CHECK (source_store_id != mirror_store_id)
);

CREATE INDEX idx_store_mirrors_source ON store_mirrors(source_store_id);
CREATE INDEX idx_store_mirrors_mirror ON store_mirrors(mirror_store_id);

CREATE TRIGGER update_store_mirrors_updated_at BEFORE UPDATE ON store_mirrors
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Shopify local data sync (per-store mirror of customers/orders for local reports)
CREATE TABLE shopify_sync_state (
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

CREATE TRIGGER update_shopify_sync_state_updated_at BEFORE UPDATE ON shopify_sync_state
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE shopify_customers (
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

CREATE INDEX idx_shopcust_store_created ON shopify_customers(store_id, created_at);
CREATE INDEX idx_shopcust_email ON shopify_customers(email_normalized);
CREATE INDEX idx_shopcust_namekey ON shopify_customers (
    ((btrim(regexp_replace(lower(coalesce(first_name, '')), '\s+', ' ', 'g')) || '|' ||
      btrim(regexp_replace(lower(coalesce(last_name, '')), '\s+', ' ', 'g'))))
);
CREATE INDEX idx_shopcust_synced ON shopify_customers(store_id, synced_at);

CREATE TABLE shopify_orders (
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
    current_subtotal_price NUMERIC(14,2),
    current_total_price NUMERIC(14,2),
    total_discounts NUMERIC(14,2),
    total_refunded NUMERIC(14,2),
    total_shipping NUMERIC(14,2),
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

CREATE INDEX idx_shoporder_completed
    ON shopify_orders(store_id, customer_shopify_id, created_at)
    WHERE cancelled_at IS NULL AND financial_status IS DISTINCT FROM 'REFUNDED';
CREATE INDEX idx_shoporder_store_created ON shopify_orders(store_id, created_at);
CREATE INDEX idx_shoporder_synced ON shopify_orders(store_id, synced_at);
CREATE INDEX idx_shoporder_customer ON shopify_orders(store_id, customer_shopify_id);

CREATE TABLE shopify_order_line_items (
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
    current_quantity INTEGER,
    original_unit_price NUMERIC(14,2),
    discounted_total NUMERIC(14,2),
    raw JSONB,
    UNIQUE (store_id, shopify_id),
    FOREIGN KEY (store_id, order_shopify_id)
        REFERENCES shopify_orders(store_id, shopify_id) ON DELETE CASCADE
);

CREATE INDEX idx_sholi_order ON shopify_order_line_items(store_id, order_shopify_id);

-- Business Overview dashboard configuration (singleton; migration 019)
CREATE TABLE IF NOT EXISTS business_overview_config (
    id SERIAL PRIMARY KEY,
    sales_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    sales_store_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    purchases_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    shopify_store_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    quotation_statuses JSONB NOT NULL DEFAULT '["In Progress","Locked"]'::jsonb,
    timezone VARCHAR(64) NOT NULL DEFAULT 'America/Chicago',
    alert_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_business_overview_config_singleton
    ON business_overview_config ((true));

CREATE TRIGGER update_business_overview_config_updated_at
    BEFORE UPDATE ON business_overview_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Business Overview — Shopify product exclusions (migration 022)
CREATE TABLE IF NOT EXISTS business_overview_shopify_exclusions (
    id SERIAL PRIMARY KEY,
    store_id INTEGER REFERENCES stores(id) ON DELETE CASCADE,
    variant_shopify_id BIGINT,
    product_shopify_id BIGINT,
    barcode TEXT,
    sku TEXT,
    title TEXT,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bov_shopify_excl_unique
    ON business_overview_shopify_exclusions (COALESCE(store_id, 0), COALESCE(variant_shopify_id, 0), COALESCE(product_shopify_id, 0), COALESCE(barcode, ''));

-- Business Overview — purchase-order product exclusions (migration 024)
CREATE TABLE IF NOT EXISTS business_overview_po_product_exclusions (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL,
    product_sku TEXT,
    product_upc TEXT,
    description TEXT,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bov_po_excl_unique
    ON business_overview_po_product_exclusions (store_id, product_id);

-- QuickBooks Online connection (singleton; migration 025)
CREATE TABLE IF NOT EXISTS quickbooks_connection (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(255),
    client_secret VARCHAR(255),
    environment VARCHAR(20) NOT NULL DEFAULT 'production',
    redirect_uri TEXT,
    realm_id VARCHAR(64),
    company_name TEXT,
    access_token TEXT,
    access_token_expires_at TIMESTAMPTZ,
    refresh_token TEXT,
    refresh_token_expires_at TIMESTAMPTZ,
    oauth_state VARCHAR(128),
    oauth_state_created_at TIMESTAMPTZ,
    status VARCHAR(30) NOT NULL DEFAULT 'disconnected',
    last_error TEXT,
    refresh_minutes INTEGER NOT NULL DEFAULT 15,
    connected_at TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_quickbooks_connection_singleton
    ON quickbooks_connection ((true));

CREATE TRIGGER update_quickbooks_connection_updated_at
    BEFORE UPDATE ON quickbooks_connection
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- QuickBooks Online account balance cache (migration 025)
CREATE TABLE IF NOT EXISTS quickbooks_accounts (
    id SERIAL PRIMARY KEY,
    qbo_id VARCHAR(64) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    fully_qualified_name TEXT,
    account_type VARCHAR(50) NOT NULL,
    account_sub_type VARCHAR(80),
    current_balance NUMERIC(16,2) NOT NULL DEFAULT 0,
    current_balance_with_sub_accounts NUMERIC(16,2),
    sub_account BOOLEAN NOT NULL DEFAULT FALSE,
    parent_qbo_id VARCHAR(64),
    currency VARCHAR(10),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    hidden BOOLEAN NOT NULL DEFAULT FALSE,
    synced_at TIMESTAMPTZ
);

-- Insert default settings
INSERT INTO settings (key, value, description) VALUES
    ('app_name', 'Global UPC', 'Application name'),
    ('version', '1.0.0', 'Application version');

-- Active clients tracking (migration 026)
CREATE TABLE IF NOT EXISTS active_clients (
    ip TEXT PRIMARY KEY,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_count BIGINT NOT NULL DEFAULT 0,
    last_section TEXT
);

CREATE INDEX IF NOT EXISTS idx_active_clients_last_seen
    ON active_clients (last_seen);
