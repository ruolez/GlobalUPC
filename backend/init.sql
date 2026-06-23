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

-- Shopify store connections (using Admin API key)
CREATE TABLE shopify_connections (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    shop_domain VARCHAR(255) NOT NULL,
    admin_api_key VARCHAR(512) NOT NULL,
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

-- Insert default settings
INSERT INTO settings (key, value, description) VALUES
    ('app_name', 'Global UPC', 'Application name'),
    ('version', '1.0.0', 'Application version');
