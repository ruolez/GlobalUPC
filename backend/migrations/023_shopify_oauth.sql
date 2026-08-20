-- Migration: Shopify OAuth client credentials grant (dual auth mode)
-- Version: 023
-- Adds per-store OAuth app credentials; admin_api_key doubles as the current
-- access token (permanent shpat_ for token mode, cached 24h token for OAuth).

ALTER TABLE shopify_connections
    ADD COLUMN IF NOT EXISTS auth_method VARCHAR(30) NOT NULL DEFAULT 'token',
    ADD COLUMN IF NOT EXISTS client_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS client_secret VARCHAR(255),
    ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ;

ALTER TABLE shopify_connections ALTER COLUMN admin_api_key DROP NOT NULL;
