-- ============================================================================
-- TrendRadar 2.0 — Opportunities Table Migration
-- PRD-v2.md Section 5.3: Analyzed Layer (Supabase PostgreSQL)
-- ============================================================================

-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Table: opportunities
-- AI-analyzed events with scores, reasoning, and action recommendations
-- ============================================================================
CREATE TABLE IF NOT EXISTS opportunities (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            VARCHAR(255) NOT NULL,          -- FK to DynamoDB event_id (stored as string)
    opportunity_type    VARCHAR(100) NOT NULL,           -- 'fast_follow', 'innovation', 'infrastructure', 'meta_tool'
    score               SMALLINT NOT NULL CHECK (score >= 0 AND score <= 100),
    score_breakdown     JSONB NOT NULL DEFAULT '{}',     -- {"pain_density": N, "tech_feasibility": N, "timing": N}
    imitation_difficulty VARCHAR(20) NOT NULL
                        CHECK (imitation_difficulty IN ('easy', 'medium', 'hard')),
    suggested_action    TEXT,
    reasoning           TEXT,                            -- AI reasoning text
    references          JSONB NOT NULL DEFAULT '[]',     -- [{source, url, snippet}]
    is_actionable       BOOLEAN NOT NULL DEFAULT false,
    status              VARCHAR(50) NOT NULL DEFAULT 'new'
                        CHECK (status IN ('new', 'reviewing', 'validated', 'passed', 'building')),
    pain_points         JSONB NOT NULL DEFAULT '[]',     -- Extracted pain points
    target_market       VARCHAR(255),                    -- e.g., 'US SMB', 'Enterprise', 'Developers'
    tech_stack_hint     JSONB NOT NULL DEFAULT '[]',     -- Suggested tech stack
    analyzed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Vector embedding column: 1536-dim from OpenAI text-embedding-3-small
    embedding           vector(1536)
);

-- ============================================================================
-- Indexes for common query patterns
-- ============================================================================

-- High-score actionable opportunities (most common query: top opportunities)
CREATE INDEX idx_opportunities_score
    ON opportunities (score DESC)
    WHERE is_actionable = true;

-- Filter by opportunity type (fast_follow, innovation, etc.)
CREATE INDEX idx_opportunities_type
    ON opportunities (opportunity_type);

-- Filter by status workflow (new → reviewing → validated → passed → building)
CREATE INDEX idx_opportunities_status
    ON opportunities (status);

-- Time-ordered analysis results (most recent first)
CREATE INDEX idx_opportunities_analyzed_at
    ON opportunities (analyzed_at DESC);

-- Lookup by DynamoDB event_id (traceability)
CREATE INDEX idx_opportunities_event_id
    ON opportunities (event_id);

-- ============================================================================
-- Vector similarity search index (IVFFlat for approximate nearest neighbor)
-- Used for semantic dedup and similarity queries
-- ============================================================================
CREATE INDEX idx_opportunities_embedding
    ON opportunities
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ============================================================================
-- Auto-update updated_at timestamp
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_opportunities_updated_at
    BEFORE UPDATE ON opportunities
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
