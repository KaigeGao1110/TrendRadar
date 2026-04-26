-- TrendRadar v2.1 Schema Migration
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor)

-- ============================================================
-- 1a. Enable pgvector extension
-- ============================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 1b. pain_signals table
-- ============================================================
CREATE TABLE IF NOT EXISTS pain_signals (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pain_text         TEXT NOT NULL,
    source            VARCHAR(50) NOT NULL,
    source_id         VARCHAR(255),
    source_url        TEXT,
    embedding         vector(2048),
    confidence        SMALLINT DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
    volume_score      SMALLINT DEFAULT 0,
    quality_score     REAL DEFAULT 0,
    cross_source_count SMALLINT DEFAULT 0,
    market_bonus      SMALLINT DEFAULT 0,
    cluster_id        UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pain_signals_confidence ON pain_signals(confidence DESC);

-- ============================================================
-- 1c. opportunity_clusters table
-- ============================================================
CREATE TABLE IF NOT EXISTS opportunity_clusters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT,
    pain_score      SMALLINT CHECK (pain_score BETWEEN 0 AND 100),
    tech_score      SMALLINT CHECK (tech_score BETWEEN 0 AND 100),
    timing_score    SMALLINT CHECK (timing_score BETWEEN 0 AND 100),
    total_score     SMALLINT CHECK (total_score BETWEEN 0 AND 100),
    confidence      SMALLINT CHECK (confidence BETWEEN 0 AND 100),
    is_actionable   BOOLEAN DEFAULT false,
    user_rating     SMALLINT CHECK (user_rating BETWEEN 1 AND 10),
    reasoning       TEXT,
    related_events  JSONB DEFAULT '[]',
    embedding       vector(2048),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clusters_score ON opportunity_clusters(total_score DESC) WHERE is_actionable = true;

-- ============================================================
-- 1d. RPC function for pgvector similarity search
-- ============================================================
CREATE OR REPLACE FUNCTION match_pain_signals(
    query_embedding vector(2048),
    match_threshold float DEFAULT 0.45,
    match_count int DEFAULT 10
)
RETURNS TABLE (
    id UUID,
    pain_text TEXT,
    source VARCHAR,
    confidence SMALLINT,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ps.id,
        ps.pain_text,
        ps.source,
        ps.confidence,
        1 - (ps.embedding <=> query_embedding) AS similarity
    FROM pain_signals ps
    WHERE 1 - (ps.embedding <=> query_embedding) > match_threshold
    ORDER BY ps.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
