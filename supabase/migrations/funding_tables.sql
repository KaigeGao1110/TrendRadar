-- Funding Analysis Engine - Supabase Tables
-- Run this in Supabase SQL Editor

-- 1. Funding Events (individual events, deduplicated)
CREATE TABLE IF NOT EXISTS funding_events (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    company text NOT NULL,
    amount_m numeric NOT NULL DEFAULT 0,
    valuation_m numeric,
    categories text[] NOT NULL DEFAULT '{}',
    url text,
    source text NOT NULL DEFAULT 'fundbat',
    first_seen_at timestamptz NOT NULL,
    investors text[] NOT NULL DEFAULT '{}',
    updated_at timestamptz DEFAULT now(),
    
    -- Unique constraint for dedup
    UNIQUE(company, amount_m, first_seen_at)
);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_funding_events_first_seen ON funding_events(first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_funding_events_amount ON funding_events(amount_m DESC);
CREATE INDEX IF NOT EXISTS idx_funding_events_categories ON funding_events USING GIN(categories);

-- 2. Funding Snapshots (daily analysis snapshots)
CREATE TABLE IF NOT EXISTS funding_snapshots (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    snapshot_type text NOT NULL,
    snapshot_date date NOT NULL DEFAULT CURRENT_DATE,
    data jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz DEFAULT now(),
    
    -- One snapshot per type per day
    UNIQUE(snapshot_type, snapshot_date)
);

-- Index for trend comparison queries
CREATE INDEX IF NOT EXISTS idx_funding_snapshots_type_date ON funding_snapshots(snapshot_type, snapshot_date DESC);

-- 3. Enable RLS (Row Level Security)
ALTER TABLE funding_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE funding_snapshots ENABLE ROW LEVEL SECURITY;

-- 4. Allow service key full access (for the script)
CREATE POLICY "Service key full access" ON funding_events FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service key full access" ON funding_snapshots FOR ALL USING (true) WITH CHECK (true);
