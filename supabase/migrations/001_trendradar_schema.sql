-- TrendRadar Supabase Schema Migration
-- Run this in the Supabase SQL Editor or via migrations

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Snapshots table: stores raw trend snapshots per source
CREATE TABLE IF NOT EXISTS snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(100) NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Digests table: stores generated trend digests
CREATE TABLE IF NOT EXISTS digests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(50) NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Trend history table: stores time-series metric values
CREATE TABLE IF NOT EXISTS trend_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(100) NOT NULL,
    metric_name VARCHAR(255) NOT NULL,
    metric_value DECIMAL(20, 6) NOT NULL,
    recorded_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_snapshots_source ON snapshots(source);
CREATE INDEX IF NOT EXISTS idx_snapshots_created_at ON snapshots(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_source_created ON snapshots(source, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_digests_type ON digests(type);
CREATE INDEX IF NOT EXISTS idx_digests_created_at ON digests(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_digests_type_created ON digests(type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trend_history_source ON trend_history(source);
CREATE INDEX IF NOT EXISTS idx_trend_history_metric_name ON trend_history(metric_name);
CREATE INDEX IF NOT EXISTS idx_trend_history_recorded_at ON trend_history(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_trend_history_source_metric ON trend_history(source, metric_name, recorded_at DESC);
