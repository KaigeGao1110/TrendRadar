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
