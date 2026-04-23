# TrendRadar v2 Architecture

TrendRadar v2 uses a three-layer data architecture to separate collection, normalization, and analysis concerns.

## Layered Flow

```
+--------------------------+
| Layer 1: S3 Raw          |
| s3://trendradar-raw      |
| Source snapshots (JSON)  |
+------------+-------------+
             |
             v
+--------------------------+
| Layer 2: DynamoDB Cleaned|
| trendradar-events        |
| trendradar-event-sources |
| Deduped canonical events |
+------------+-------------+
             |
             v
+--------------------------+
| Layer 3: Supabase        |
| Analyzed opportunities   |
| Scored + enriched output |
+--------------------------+
```

## Data Flow

```
[Collectors]
  YC / Product Hunt / HN / VC feeds
          |
          v
[Layer 1: S3 Raw]
  Immutable batch snapshots
          |
          v
[Normalization + Dedup]
  Parse -> standardize -> merge
          |
          v
[Layer 2: DynamoDB Cleaned]
  Canonical events + source mapping
          |
          v
[AI Analysis Pipeline]
  Opportunity extraction + scoring
          |
          v
[Layer 3: Supabase Analyzed]
  Query-ready records for API/UI
```

## Layer Purpose And Components

### Layer 1: S3 Raw
- Purpose: Durable landing zone for unmodified source payloads.
- Components: `s3://trendradar-raw/{source}/{date}/{batch_id}.json`.
- Why it exists: Preserves provenance and supports replay/backfill.

### Layer 2: DynamoDB Cleaned
- Purpose: Operational store for normalized, deduplicated events.
- Components:
- `trendradar-events`: canonical event records keyed by `event_type#first_seen_date` + `event_id`.
- `trendradar-event-sources`: mapping from `raw_signal_id` to `event_id` for traceability.
- Why it exists: Fast keyed reads/writes for pipeline state and event lifecycle.

### Layer 3: Supabase Analyzed
- Purpose: Analytics and application-serving layer for analyzed opportunities.
- Components: Relational tables for scored insights, metadata, and downstream querying.
- Why it exists: SQL-friendly access patterns for dashboard, API responses, and reporting.

---

## Phase 2: AI Analysis Engine

### New Components

#### `analyzer/pipeline.py`
Fetches unanalyzed events from DynamoDB, computes embeddings, deduplicates via vector similarity, scores events, and writes results to Supabase `opportunities` table.

#### `analyzer/scoring.py`
Implements scoring formulas from PRD Section 7.3:
- `compute_pain_density(event)` → 0-100
- `compute_tech_feasibility(event)` → 0-100
- `compute_timing(event)` → 0-100
- `compute_total_score(breakdown)` → 0-100 (weighted: pain 40%, tech 30%, timing 30%)
- `classify_opportunity_type(event, breakdown)` → fast_follow | innovation | infrastructure | meta_tool
- `classify_imitation_difficulty(event, type, breakdown)` → easy | medium | hard
- `score_to_label(score)` → very_high | high | medium | low | ignore

#### `analyzer/dedup.py`
Deduplication via Supabase IVFFlat vector search:
- `cosine_similarity(a, b)` — pure Python cosine similarity
- `find_similar_opportunities(supabase_client, embedding)` — queries existing opportunities by vector similarity
- `should_merge(event, similar_opportunities)` — returns merge decision dict

#### `analyzer/reasoning.py`
LLM-based reasoning and suggested action generation:
- `generate_reasoning(anthropic_client, event_text, score_breakdown, opp_type, imitation_diff)` — 2-3 sentence reasoning
- `generate_suggested_action(anthropic_client, event_text, opp_type, imitation_diff, total_score)` — JSON with next_step, validation_path, recommended_stack
- Fallback generation when LLM unavailable

#### `analyzer/cron.py`
Analysis cron trigger mechanism:
- `run_analysis(limit, dry_run)` — full pipeline runner
- `lambda_handler(event, context)` — AWS Lambda entry point for EventBridge-triggered analysis
- CLI: `python -m analyzer.cron --limit 50`

#### `tests/test_scoring.py`
40 unit tests covering all scoring functions with mocked event data.

### Opportunities Table

```sql
CREATE TABLE IF NOT EXISTS opportunities (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            VARCHAR(255) NOT NULL,
    opportunity_type    VARCHAR(100) NOT NULL,
    score               SMALLINT NOT NULL CHECK (score >= 0 AND score <= 100),
    score_breakdown     JSONB NOT NULL DEFAULT '{}',
    imitation_difficulty VARCHAR(20) NOT NULL,
    suggested_action    TEXT,
    reasoning           TEXT,
    references          JSONB NOT NULL DEFAULT '[]',
    is_actionable       BOOLEAN NOT NULL DEFAULT false,
    status              VARCHAR(50) NOT NULL DEFAULT 'new',
    pain_points         JSONB NOT NULL DEFAULT '[]',
    target_market       VARCHAR(255),
    tech_stack_hint     JSONB NOT NULL DEFAULT '[]',
    analyzed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding           vector(1536)
);
-- IVFFlat index for vector similarity search
CREATE INDEX idx_opportunities_embedding ON opportunities
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### Cron Schedule

| Job | Frequency | Trigger | Action |
|-----|-----------|---------|--------|
| Batch AI analysis | Every 30 min | EventBridge / cron | Fetch unanalyzed events → score → write Supabase |
| High-severity immediate analysis | DynamoDB Streams | Lambda trigger | Score severity ≥ 8 events immediately |
