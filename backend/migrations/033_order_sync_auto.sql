-- Migration: Order Sync automation
-- Version: 033
-- Date: 2026-09-28
-- Description: One daily job that compares yesterday's BackOffice invoices
--              with the Shopify orders and runs the switched-on Order Sync
--              steps. `order_sync_auto_config` is the singleton schedule;
--              `order_sync_auto_runs` is one row per run with its live
--              progress and final report. Two partial unique indexes make the
--              4 prod workers safe: at most one run per schedule day
--              (`slot_date`) and at most one run `running` at a time.

CREATE TABLE IF NOT EXISTS order_sync_auto_config (
    id SERIAL PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    run_time VARCHAR(5) NOT NULL DEFAULT '06:00',       -- HH:MM, shop time zone
    days INTEGER[] NOT NULL DEFAULT '{0,1,2,3,4,5,6}',  -- Python weekday(), 0 = Monday
    timezone VARCHAR(64),                               -- the Shopify store's IANA zone
    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
    steps JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_from TIMESTAMPTZ,                         -- slots before this never run
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_sync_auto_runs (
    id SERIAL PRIMARY KEY,
    trigger VARCHAR(16) NOT NULL,                       -- scheduled | catch_up | manual
    slot_date DATE,                                     -- schedule day; NULL for manual runs
    run_date DATE,                                      -- the day reconciled
    status VARCHAR(16) NOT NULL,                        -- running | succeeded | partial | failed | stopped | missed
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    options JSONB,                                      -- the steps this run used
    phase VARCHAR(255),
    progress JSONB,
    summary_before JSONB,
    summary_after JSONB,
    report JSONB,
    counts JSONB,
    stop_requested BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    heartbeat_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_order_sync_auto_runs_slot
    ON order_sync_auto_runs (slot_date) WHERE slot_date IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_order_sync_auto_runs_running
    ON order_sync_auto_runs ((TRUE)) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_order_sync_auto_runs_started
    ON order_sync_auto_runs (started_at DESC);
