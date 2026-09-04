-- Migration: Active clients tracking
-- Version: 026
-- Date: 2026-09-04
-- Description: Per-IP activity tracking so operators can see who is using the
--              app before deploying an update. Rows are upserted in batches by
--              a background flush loop in the backend; first_seen is reset when
--              the IP returns after a 30-minute gap (a new "session"). Rows
--              idle for more than 24 hours are pruned by the same loop.

CREATE TABLE IF NOT EXISTS active_clients (
    ip TEXT PRIMARY KEY,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_count BIGINT NOT NULL DEFAULT 0,
    last_section TEXT
);

CREATE INDEX IF NOT EXISTS idx_active_clients_last_seen
    ON active_clients (last_seen);

-- Idempotent column add for databases where the table pre-dates last_section
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_name = 'active_clients' AND column_name = 'last_section'
    ) THEN
        ALTER TABLE active_clients ADD COLUMN last_section TEXT;
    ELSE
        RAISE NOTICE 'active_clients.last_section already exists, skipping';
    END IF;
END $$;
