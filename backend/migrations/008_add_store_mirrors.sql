-- Store mirrors table
CREATE TABLE IF NOT EXISTS store_mirrors (
    id SERIAL PRIMARY KEY,
    source_store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    mirror_store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_store_id, mirror_store_id),
    CHECK (source_store_id != mirror_store_id)
);

CREATE INDEX IF NOT EXISTS idx_store_mirrors_source ON store_mirrors(source_store_id);
CREATE INDEX IF NOT EXISTS idx_store_mirrors_mirror ON store_mirrors(mirror_store_id);

-- Trigger for updated_at (idempotent via DO block)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_store_mirrors_updated_at') THEN
        CREATE TRIGGER update_store_mirrors_updated_at BEFORE UPDATE ON store_mirrors
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- Mirror tracking columns on price_update_history
ALTER TABLE price_update_history ADD COLUMN IF NOT EXISTS is_mirror BOOLEAN DEFAULT false;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='price_update_history' AND column_name='mirror_source_store_id') THEN
        ALTER TABLE price_update_history ADD COLUMN mirror_source_store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL;
    END IF;
END $$;
