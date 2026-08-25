-- Migration: QuickBooks Online integration
-- Version: 025
-- Date: 2026-08-25
-- Description: Singleton QuickBooks Online connection (Intuit app keys,
--              OAuth 2.0 tokens, connected company) plus a local cache of the
--              Bank / Credit Card account balances shown on Business Overview.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'quickbooks_connection') THEN
        CREATE TABLE quickbooks_connection (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(255),
            client_secret VARCHAR(255),
            environment VARCHAR(20) NOT NULL DEFAULT 'production',      -- production | sandbox
            redirect_uri TEXT,
            realm_id VARCHAR(64),
            company_name TEXT,
            access_token TEXT,
            access_token_expires_at TIMESTAMPTZ,
            refresh_token TEXT,
            refresh_token_expires_at TIMESTAMPTZ,
            oauth_state VARCHAR(128),
            oauth_state_created_at TIMESTAMPTZ,
            status VARCHAR(30) NOT NULL DEFAULT 'disconnected',         -- disconnected | connected | needs_reconnect
            last_error TEXT,
            refresh_minutes INTEGER NOT NULL DEFAULT 15,
            connected_at TIMESTAMPTZ,
            last_synced_at TIMESTAMPTZ,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Only one connection row allowed
        CREATE UNIQUE INDEX idx_quickbooks_connection_singleton
            ON quickbooks_connection ((true));

        CREATE TRIGGER update_quickbooks_connection_updated_at
            BEFORE UPDATE ON quickbooks_connection
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

        RAISE NOTICE 'Created quickbooks_connection table';
    ELSE
        RAISE NOTICE 'Table quickbooks_connection already exists, skipping';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quickbooks_accounts (
    id SERIAL PRIMARY KEY,
    qbo_id VARCHAR(64) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    fully_qualified_name TEXT,
    account_type VARCHAR(50) NOT NULL,               -- Bank | Credit Card
    account_sub_type VARCHAR(80),
    current_balance NUMERIC(16,2) NOT NULL DEFAULT 0,
    current_balance_with_sub_accounts NUMERIC(16,2),
    sub_account BOOLEAN NOT NULL DEFAULT FALSE,
    parent_qbo_id VARCHAR(64),
    currency VARCHAR(10),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    hidden BOOLEAN NOT NULL DEFAULT FALSE,           -- user toggle, preserved across syncs
    synced_at TIMESTAMPTZ
);
