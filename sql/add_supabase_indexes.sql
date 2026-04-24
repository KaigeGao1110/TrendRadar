-- Add required indexes to Supabase tables for better performance

-- 1. Add GIN index on snapshots.data for fast keyword search (if you keep snapshots table)
-- CREATE INDEX idx_snapshots_data ON snapshots USING GIN (data jsonb_path_ops);

-- 2. Add composite index on trend_history for fast date range queries
CREATE INDEX idx_trend_history_source_metric_date ON trend_history (source, metric_name, recorded_at);

-- 3. Add index on digests for fast latest digest queries
CREATE INDEX idx_digests_created_at ON digests (created_at DESC);

-- 4. Add unique constraint on digests to avoid duplicate digests for same date/type
ALTER TABLE digests ADD CONSTRAINT unique_digest_per_type_date UNIQUE (type, created_at::date);
