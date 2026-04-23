# TrendRadar 2.0 — Product Requirements Document

**Version:** 2.0
**Date:** 2026-04-22
**Author:** TrendRadar Product Team
**Status:** Draft
**Supabase Instance:** `https://sedwocbnyneberhsuhdr.supabase.co`

---

## 1. Executive Summary

TrendRadar 2.0 is a major architectural upgrade to the existing TrendRadar MVP. Where v1 was a trend-monitoring tool with 4 data sources and basic keyword detection, **v2 is built to power a "Fast Imitation" strategy** — the ability to detect validated market demand and rapidly follow up with a competitive copy.

The core value proposition: **turn raw market signals into scored, actionable opportunities in near real-time**, with an AI agent layer that continuously monitors, deduplicates, scores, and pushes high-value opportunities before they become crowded.

Key changes from v1:
- Three-tier hybrid storage (S3 → DynamoDB → Supabase) replacing flat JSON + single Supabase
- 4 existing sources expanded to 15+ sources (MCP, API, RSS, scraping)
- AI-powered deduplication, scoring, and opportunity judgment replacing keyword-based detection
- OpenClaw Agent integration for natural-language opportunity queries
- Telegram push for high-value signals, replacing (or augmenting) Slack-only delivery

---

## 2. Product Goal

**Mission:** Be the fastest signal-to-action pipeline for solo founders running a "copy-validated-products" strategy in the US market.

**Specific objectives:**
1. Ingest 15+ raw data sources continuously (cron-driven, ~15-min intervals)
2. Deduplicate and normalize signals into clean `events` stored in DynamoDB
3. Run AI analysis (via OpenClaw Agent) to score each event on pain density, technical feasibility, and timing
4. Surface scores and reasoning in Supabase for agent-style querying
5. Push high-score opportunities (≥70/100) to Telegram instantly
6. Deliver daily/weekly digests covering all active opportunities

**Out of scope for v2:**
- Automated product generation or landing page cloning
- User accounts, auth, or personalization
- Non-English market signals

---

## 3. User Scenarios

### Scenario 1: Morning Opportunity Scan
> Kaige wakes up, opens Telegram. TrendRadar has pushed 2 high-value signals from overnight (score ≥70). He reads the AI reasoning for each, decides one is worth pursuing. He asks OpenClaw: "give me the full analysis for opportunity #tr-2026-0422-0017" — gets a structured brief with references.

### Scenario 2: Directed Query
> Kaige is exploring "AI legal tools." He opens OpenClaw and types: "What are the highest-scoring opportunities in AI legal tools from the last 30 days?" The agent queries Supabase and returns a ranked list with scores, pain points, and suggested actions.

### Scenario 3: Weekly Strategic Review
> Every Monday, Kaige reviews the weekly digest. It shows trending pain points, new entrants in his target categories, VC funding concentration, and a ranked list of the top 10 opportunities from the past week.

### Scenario 4: Competitive Landscape Check
> Before starting a new project, Kaige asks: "Has anyone recently launched something in the AI meeting notes space? What's the imitation difficulty?" TrendRadar returns recent events related to that space, including funding rounds, HN discussions, and PH launches.

---

## 4. System Architecture (ASCII)

```
┌─────────────────────────────────────────────────────────────────┐
│                        TRENDRADAR 2.0                           │
│                     FULL DATA FLOW                              │
└─────────────────────────────────────────────────────────────────┘

  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
  │    YC    │   │   PH     │   │    HN    │   │  VC Fund │
  │  (API)   │   │  (API)   │   │  (MCP)   │   │  (API)   │
  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘
       │              │              │               │
  ┌────▼──────────────▼──────────────▼───────────────▼─────┐
  │              RAW INGESTION LAYER                        │
  │           AWS S3  (s3://trendradar-raw/)                │
  │                                                        │
  │  s3://trendradar-raw/{source}/{date}/{batch_id}.json   │
  │                                                        │
  │  Each JSON = full cron scrape output, immutable        │
  └────────────────────────┬───────────────────────────────┘
                           │ S3 Write (per-source, per-cron)
  ┌────────────────────────▼───────────────────────────────┐
  │              CLEANING & DEDUP LAYER                    │
  │           AWS DynamoDB  (events table)                 │
  │                                                        │
  │  Table: events                                         │
  │    PK: event_type#first_seen_date                      │
  │    SK: event_id                                        │
  │                                                        │
  │  Table: event_sources                                  │
  │    PK: raw_signal_id                                   │
  │    SK: event_id                                        │
  │                                                        │
  │  Dedup: keyword+entity extraction →                     │
  │         embedding similarity > 0.85 OR entity match     │
  └────────────────────────┬───────────────────────────────┘
                           │ DynamoDB Write (cleaned events)
  ┌────────────────────────▼───────────────────────────────┐
  │              AI ANALYSIS LAYER                         │
  │         OpenClaw Agent (cron-triggered)                │
  │                                                        │
  │  1. Fetch new events from DynamoDB                    │
  │  2. Score: pain_density(40%) + tech_feasibility(30%)  │
  │           + timing(30%)                                │
  │  3. Determine opportunity_type, imitation_difficulty   │
  │  4. Write to Supabase opportunities table             │
  │  5. If score >= 70 → trigger Telegram push            │
  └────────────────────────┬───────────────────────────────┘
                           │ Supabase Write (analyzed)
  ┌────────────────────────▼───────────────────────────────┐
  │              ANALYZED STORAGE LAYER                    │
  │    Supabase PostgreSQL                                 │
  │    (https://sedwocbnyneberhsuhdr.supabase.co)          │
  │                                                        │
  │  Table: opportunities                                  │
  │  Table: snapshots (existing, preserved)                │
  │  Table: digests   (existing, preserved)                │
  └────────────────────────┬───────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
  ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
  │   Telegram   │   │ OpenClaw    │   │   Slack     │
  │   Push Bot   │   │   Agent     │   │  Digest Bot │
  │ (score >=70) │   │ (on-demand  │   │ (daily+wkly)│
  │              │   │  queries)   │   │             │
  └──────────────┘   └─────────────┘   └─────────────┘
```

---

## 5. Three-Layer Storage Design

### 5.1 Raw Layer — AWS S3

**Purpose:** Immutable cold storage for all original scrapes. Write-once, never modify or delete.

**S3 Bucket:** `s3://trendradar-raw`

**Path Structure:**
```
s3://trendradar-raw/{source}/{YYYY-MM-DD}/{batch_id}.json
```

**Path Variables:**
- `source`: lowercase source identifier (e.g., `ycombinator`, `producthunt`, `reddit-startups`, `github-trending`)
- `YYYY-MM-DD`: ISO date of the crawl (UTC)
- `batch_id`: `{source}-{timestamp}-{uuid_short}` (e.g., `yc-20260422-a1b2c3d4`)

**JSON File Structure (example for YC):**
```json
{
  "metadata": {
    "source": "ycombinator",
    "fetched_at": "2026-04-22T14:30:00Z",
    "batch_id": "yc-20260422-a1b2c3d4",
    "item_count": 47,
    "fetch_duration_ms": 2341,
    "status": "success"
  },
  "raw_items": [
    {
      "id": "yc-w24-001",
      "name": "ExampleCorp",
      "one_liner": "AI-powered code review",
      "batch": "W24",
      "url": "https://www.ycombinator.com/companies/examplecorp"
    }
  ]
}
```

**Lifecycle Policy:**
- Move to S3 Glacier after 90 days
- Delete after 365 days (raw data is preserved in cleaned DynamoDB records)

**S3 to DynamoDB Ingestion Flow:**
1. Source fetcher writes raw JSON to S3
2. Lambda triggered on S3 PUT (or cron steps through S3 prefix)
3. Lambda reads JSON, extracts and normalizes items
4. Lambda writes cleaned records to DynamoDB `events` table
5. Lambda links raw signals to events via `event_sources` table

---

### 5.2 Cleaned Layer — AWS DynamoDB

**Purpose:** High-throughput, flexible-schema storage for deduplicated and normalized events. The "working set" of all market signals.

#### Table 1: `events`

**Partition Key (PK):** `event_type#first_seen_date` (String)
**Sort Key (SK):** `event_id` (String)

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `event_type` | String | Category: `startup_launch`, `funding_round`, `product_update`, `viral_post`, `reddit_discussion`, `news_article`, `github_trending`, `newsletter_highlight` |
| `first_seen_date` | String | ISO date `YYYY-MM-DD` (partition key component) |
| `event_id` | String | UUID v4 (sort key component) |
| `title` | String | Normalized title/name of the event |
| `description` | String | One-line description or tagline |
| `url` | String | Canonical URL |
| `categories` | List[String] | Industry tags (e.g., `["AI", "Legal", "B2B"]`) |
| `keywords` | List[String] | Extracted keywords for dedup |
| `entities` | Map[String, String] | Named entities: `{"company": "...", "product": "..."}` |
| `severity` | Number | 1-10, raw signal strength |
| `first_seen_at` | String | ISO timestamp of first appearance |
| `last_seen_at` | String | ISO timestamp of last appearance |
| `signal_count` | Number | Number of source mentions |
| `source_ids` | List[String] | List of `raw_signal_id` references |
| `embedding` | List[Number] | Vector embedding for similarity search (1536-dim for OpenAI `text-embedding-3-small`, or 256-dim for lighter weight) |
| `is_analyzed` | Boolean | Whether AI analysis has been run |
| `ttl` | Number | DynamoDB TTL epoch (30 days from last_seen_at) |

**Global Secondary Indexes (GSIs):**

- **GSI1:** `event_id-index` on `event_id` (SK only) → for direct event lookup
- **GSI2:** `is_analyzed#first_seen_date-index` on `is_analyzed` (PK) + `first_seen_date` (SK) → find unanalyzed events for batch AI analysis
- **GSI3:** `categories-index` on `categories` (PK, multi-value) + `first_seen_date` (SK) → query by category

#### Table 2: `event_sources` (Many-to-Many)

**Partition Key (PK):** `raw_signal_id` (String)
**Sort Key (SK):** `event_id` (String)

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `raw_signal_id` | String | Unique ID from source (e.g., `hn-12345678`) |
| `event_id` | String | Associated event UUID |
| `source` | String | Source name: `ycombinator`, `producthunt`, `hackernews`, `vc_funding`, `reddit-startups`, etc. |
| `relevance_score` | Number | 0.0-1.0, per-source relevance |
| `fetched_at` | String | ISO timestamp |
| `raw_data` | Map | Original fields from that source |

**Note:** This table enables provenance tracking — for each aggregated event, you can trace back every source signal that contributed to it.

#### CDK Table Definition (TypeScript):

```typescript
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as cdk from 'aws-cdk-lib';

export class TrendRadarDynamoDBStack extends cdk.Stack {
  constructor(scope: cdk.App, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Table: events
    const eventsTable = new dynamodb.Table(this, 'EventsTable', {
      tableName: 'trendradar-events',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      timeToLiveAttribute: 'ttl',
    });

    eventsTable.addGlobalSecondaryIndex({
      indexName: 'event_id-index',
      partitionKey: { name: 'event_id', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    eventsTable.addGlobalSecondaryIndex({
      indexName: 'is_analyzed-first_seen_date-index',
      partitionKey: { name: 'is_analyzed', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'first_seen_date', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Table: event_sources
    const eventSourcesTable = new dynamodb.Table(this, 'EventSourcesTable', {
      tableName: 'trendradar-event-sources',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
    });
  }
}
```

**Note:** The PK/SK names use generic `PK`/`SK` for DynamoDB GSI flexibility. The composite key `event_type#first_seen_date` is constructed in the application layer and stored as the PK value.

**DynamoDB Streams:**
- Enable streams on `events` table (NEW_AND_OLD_IMAGES)
- Trigger Lambda on stream → trigger OpenClaw Agent for immediate analysis of high-severity events (severity ≥ 8)

---

### 5.3 Analyzed Layer — Supabase PostgreSQL

**Purpose:** Store AI-analyzed opportunities with scores, reasoning, and action recommendations. Enables relational queries, vector similarity search, and OpenClaw Agent querying.

**Existing tables (preserved):** `snapshots`, `digests`, `trend_history`

**New table:** `opportunities`

---

#### Table: `opportunities` (New)

```sql
-- Opportunities: AI-analyzed events with scores and recommendations
CREATE TABLE IF NOT EXISTS opportunities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        VARCHAR(255) NOT NULL,          -- FK to DynamoDB event_id (stored as string)
    opportunity_type VARCHAR(100) NOT NULL,         -- 'fast_follow', 'innovation', 'infrastructure', 'meta_tool'
    score           SMALLINT NOT NULL CHECK (score >= 0 AND score <= 100),
    score_breakdown JSONB NOT NULL DEFAULT '{}',    -- {"pain_density": N, "tech_feasibility": N, "timing": N}
    imitation_difficulty VARCHAR(20) NOT NULL CHECK (imitation_difficulty IN ('easy', 'medium', 'hard')),
    suggested_action TEXT,
    reasoning       TEXT,                            -- AI reasoning text
    references      JSONB NOT NULL DEFAULT '[]',    -- [{source, url, snippet}]
    is_actionable   BOOLEAN NOT NULL DEFAULT false,
    status          VARCHAR(50) NOT NULL DEFAULT 'new'
                                           CHECK (status IN ('new', 'reviewing', 'validated', 'passed', 'building')),
    pain_points     JSONB NOT NULL DEFAULT '[]',   -- Extracted pain points
    target_market   VARCHAR(255),                   -- e.g., 'US SMB', 'Enterprise', 'Developers'
    tech_stack_hint JSONB NOT NULL DEFAULT '[]',   -- Suggested tech stack
    analyzed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for common query patterns
CREATE INDEX idx_opportunities_score ON opportunities(score DESC) WHERE is_actionable = true;
CREATE INDEX idx_opportunities_type ON opportunities(opportunity_type);
CREATE INDEX idx_opportunities_status ON opportunities(status);
CREATE INDEX idx_opportunities_analyzed_at ON opportunities(analyzed_at DESC);
CREATE INDEX idx_opportunities_event_id ON opportunities(event_id);

-- Vector similarity search (pgvector extension required)
-- Embedding column: 1536-dim from OpenAI text-embedding-3-small
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- Approximate nearest neighbor search for semantic dedup and similarity queries
CREATE INDEX idx_opportunities_embedding ON opportunities
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

**`score_breakdown` JSONB structure:**
```json
{
  "pain_density": 85,
  "tech_feasibility": 70,
  "timing": 90
}
```

**`references` JSONB structure:**
```json
[
  {
    "source": "producthunt",
    "url": "https://producthunt.com/posts/example",
    "snippet": "Solve X problem for Y audience..."
  },
  {
    "source": "vc_funding",
    "url": "...",
    "snippet": "..."
  }
]
```

**`pain_points` JSONB structure:**
```json
["Users struggle with X", "Existing solutions are too expensive for Y", "No good open source option for Z"]
```

**`tech_stack_hint` JSONB structure:**
```json
["Next.js", "Supabase", "OpenAI API", "Stripe", "TailwindCSS"]
```

---

#### Enhanced `snapshots` table (existing, minor addition):

```sql
-- Add source_url and batch_id for traceability
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS batch_id VARCHAR(255);
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS raw_s3_path TEXT;  -- e.g., s3://trendradar-raw/ycombinator/2026-04-22/batch-001.json
```

---

## 6. Data Source Inventory

### 6.1 Data Sources Summary

| # | Source | Category | Type | Collection Method | Refresh |
|---|--------|----------|------|-------------------|---------|
| 1 | Y Combinator | Startup Directories | API | `GET https://api.ycombinator.com/v0.1/companies` | Every 6h |
| 2 | Product Hunt | Product Discovery | API | PH API (requires key) or scraping | Every 4h |
| 3 | Hacker News | Tech Community | MCP | `playwright-mcp` / Firebase API | Every 15min |
| 4 | VC Funding | Funding Data | API | Crunchbase/Public APIs | Every 6h |
| 5 | Reddit (r/startups) | Community Signals | MCP | `playwright-mcp` | Every 30min |
| 6 | Reddit (r/SaaS) | Community Signals | MCP | `playwright-mcp` | Every 30min |
| 7 | Reddit (r/indiehackers) | Community Signals | MCP | `playwright-mcp` | Every 30min |
| 8 | GitHub Trending | Developer Trends | MCP | `playwright-mcp` or GitHub API | Every 1h |
| 9 | Newsletter RSS (Lenny's, TLDR, etc.) | Newsletter Highlights | RSS | Python `feedparser` | Every 2h |
| 10 | Twitter/X Keywords | Social Trends | Scraping/API | Twitter API v2 or scraping | Every 15min |
| 11 | LinkedIn Industry Posts | B2B Signals | Scraping | Selenium/playwright | Every 2h |
| 12 | AppSumo Deals | Deal/Funnel Signals | Scraping | HTTP requests + BeautifulSoup | Every 6h |
| 13 | G2 / TrustRadius | Review Site Signals | Scraping | HTTP requests + BeautifulSoup | Every 6h |
| 14 | Competitor Websites | Pricing & Features | Scraping | HTTP requests (respect robots.txt) | Every 24h |
| 15 | SearXNG | General Web Search | MCP | `playwright-mcp` + SearXNG | On-demand |

### 6.2 Collection Method Details

#### MCP Sources (via `playwright-mcp`)
- **HN:** `browser_navigate("https://news.ycombinator.com")` → extract top stories
- **Reddit:** `browser_navigate("https://reddit.com/r/startups")` → extract post titles, scores, comments
- **GitHub Trending:** `browser_navigate("https://github.com/trending")` → extract repo names, stars, descriptions

#### API Sources
- **YC:** `requests.get("https://api.ycombinator.com/v0.1/companies")` — existing, no key needed
- **VC Funding:** Crunchbase API or similar (free tier or mock). Fallback: news article scraping
- **Twitter/X:** Twitter API v2 with academic/research access, or third-party aggregator APIs (e.g., Aperture, Nitter alternatives)

#### RSS Sources
Newsletter RSS feeds to monitor:
- Lenny's Newsletter: `https://www.lennysnewsletter.com/feed`
- TLDR Newsletter: `https://tldr.tech/feed`
- Stratechery: `https://stratechery.com/feed/`
- Ben Evans Newsletter: `https://ben-evans.com/feed`
- a16z Newsletter: `https://a16z.com/feed/`
- CB Insights: `https://www.cbinsights.com/research-news/feed/`
- First Round Review: `https://firstround.com/feed/`
- Morning Brew: `https://www.morningbrew.com/feed`

#### Scraping Sources
- **AppSumo:** `https://appsumo.com` deal pages
- **G2:** `https://www.g2.com/categories/[category]` product lists
- **TrustRadius:** `https://www.trustradius.com/` category pages
- **Competitor sites:** Per-competitor landing/pricing pages

---

## 7. AI Analysis Layer Design

### 7.1 Analysis Pipeline

```
[New Raw Signals in DynamoDB]
         │
         ▼
┌─────────────────────────────────────┐
│  Step 1: Fetch unanalyzed events    │
│  (is_analyzed = false)              │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Step 2: Entity + Keyword Extraction│
│  (LLM or rule-based)               │
│  - Company name                     │
│  - Product name                    │
│  - Problem being solved            │
│  - Target user                     │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Step 3: Deduplication             │
│  - Compute embedding (OpenAI)      │
│  - Query existing events (IVFFlat)  │
│  - If cosine_sim > 0.85 OR         │
│    entity_match → MERGE into event │
│  - Else → CREATE new event         │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Step 4: Scoring                   │
│  Pain Density:  40%                │
│  Tech Feasibility: 30%              │
│  Timing:       30%                 │
│  ─────────────────                 │
│  Total Score:   0-100               │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Step 5: Opportunity Judgment      │
│  opportunity_type (categorize)     │
│  imitation_difficulty (rate)       │
│  suggested_action (text)            │
│  reasoning (text)                   │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Step 6: Write to Supabase         │
│  INSERT INTO opportunities (...)   │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Step 7: Push Decision             │
│  score >= 70 → Telegram push       │
│  score < 70  → skip (digest only)  │
└─────────────────────────────────────┘
```

### 7.2 Deduplication Logic

**Input:** A new raw signal (title, description, URL, source)

**Step 1 — Entity Extraction:**
- Use LLM or regex/NER to extract: `company_name`, `product_name`, `problem_statement`
- Example: "Launching Notion-like docs for legal teams" → `company: [newco]`, `product_type: "docs tool"`, `target_market: "legal"`

**Step 2 — Vector Embedding:**
- Encode `title + description` using `text-embedding-3-small` (1536-dim or reduced to 256-dim for cost)
- Store embedding in DynamoDB `events.embedding` field

**Step 3 — Similarity Search:**
- Query existing DynamoDB events (via Supabase IVFFlat index on stored embeddings)
- Also check DynamoDB GSI for entity matches (same company name or product type)

**Step 4 — Merge vs. Create:**
```
IF similarity > 0.85 OR (same_company AND same_product_type):
    → MERGE: add raw_signal_id to existing event's source_ids, increment signal_count, update last_seen_at
    → Run analysis update on existing event
ELSE:
    → CREATE new event
    → Mark is_analyzed = false (triggers analysis pipeline)
```

### 7.3 Scoring Formula

**Overall Score = 0-100 (integer)**

```
total_score = round(pain_density × 0.4 + tech_feasibility × 0.3 + timing × 0.3)
```

**Dimension Breakdown:**

| Dimension | Weight | What It Measures | Data Sources |
|-----------|--------|-----------------|--------------|
| **Pain Density** | 40% | How many people explicitly complain about this problem? Are signals coming from multiple independent sources? | Reddit posts, HN comments, VC discussions, reviews |
| **Tech Feasibility** | 30% | Can a solo founder build a v1 in 2-4 weeks? | Product complexity, required integrations, data dependencies |
| **Timing** | 30% | Is this a new or rapidly accelerating trend? Or is it already saturated? | First_seen_at, signal_count growth rate, YC batch trends, VC funding wave |

**Scoring Rules (per dimension, 0-100):**

**Pain Density (0-100):**
- Score 80-100: Multiple independent sources (≥3) explicitly describe the same pain
- Score 60-79: Same pain mentioned in 2 sources
- Score 40-59: Pain mentioned in 1 source but described as acute
- Score 0-39: Vague or niche pain, weak signal

**Tech Feasibility (0-100):**
- Score 80-100: No deep tech required, can use existing APIs/frameworks (e.g., LLM API + UI)
- Score 60-79: Moderate complexity, 1-2 novel integrations
- Score 40-59: Some novel tech, but achievable solo
- Score 0-39: Requires significant ML/infra work, large data sets, or complex domain expertise

**Timing (0-100):**
- Score 80-100: First signal within last 7 days, signal_count growing week-over-week
- Score 60-79: Signals within last 30 days, stable or growing
- Score 40-59: Signals in last 30-90 days, stable
- Score 0-39: Signals older than 90 days, or market already saturated (many established players)

**Imitation Difficulty (categorical):**
- `easy`: No proprietary data, no network effects, simple tech stack
- `medium`: Some data moat or integration complexity
- `hard`: Strong network effects, complex tech, regulatory hurdles

### 7.4 Opportunity Type Classification

The AI assigns one of the following `opportunity_type` values:

| Type | Description | Trigger Signals |
|------|-------------|----------------|
| `fast_follow` | Copy a proven product for a new audience or market | PH launch + VC funding + multiple Reddit complaints about price |
| `innovation` | New solution to old problem using new tech (AI) | HN trending + new YC batch entries + emerging tech keywords |
| `infrastructure` | Tool that enables other builders | Developer tools, APIs, devops, low-code |
| `meta_tool` | Tool that improves other tools | AI-assisted coding, testing, deployment tools |

### 7.5 OpenClaw Agent Analysis Prompts

**System Prompt for the TrendRadar Agent:**

```
You are TrendRadar AI, an analyst specializing in startup opportunity detection.
You have access to a Supabase PostgreSQL database with the following schema:

Table: opportunities
- id, event_id, opportunity_type, score (0-100)
- score_breakdown: {pain_density, tech_feasibility, timing} (each 0-100)
- imitation_difficulty: easy | medium | hard
- suggested_action: TEXT
- reasoning: TEXT
- references: JSONB array of {source, url, snippet}
- is_actionable: BOOLEAN
- status: new | reviewing | validated | passed | building
- pain_points: JSONB array of TEXT
- target_market: TEXT
- tech_stack_hint: JSONB array of TEXT
- analyzed_at: TIMESTAMPTZ

When a user asks about trends or opportunities:
1. Query Supabase with appropriate filters
2. Return structured results with scores and reasoning
3. Highlight which signals drove the score
4. Suggest concrete next steps

Always cite your sources (the references field in each opportunity).
```

---

## 8. OpenClaw Integration

### 8.1 Agent Queries (Text-in, Structured Data-out)

The OpenClaw Agent queries Supabase for the following scenarios:

**Query 1: High-value opportunities in the last N days**
```sql
SELECT id, event_id, opportunity_type, score, score_breakdown,
       imitation_difficulty, suggested_action, reasoning, is_actionable,
       pain_points, target_market, analyzed_at
FROM opportunities
WHERE analyzed_at >= NOW() - INTERVAL '7 days'
  AND is_actionable = true
ORDER BY score DESC
LIMIT 10;
```

**Query 2: Opportunities by type or category**
```sql
SELECT * FROM opportunities
WHERE opportunity_type = 'fast_follow'
  AND is_actionable = true
  AND analyzed_at >= NOW() - INTERVAL '30 days'
ORDER BY score DESC;
```

**Query 3: Opportunities related to a keyword (via pain_points/reasoning ILIKE)**
```sql
SELECT * FROM opportunities
WHERE (reasoning ILIKE '%legal%' OR pain_points::text ILIKE '%legal%')
  AND is_actionable = true
ORDER BY score DESC
LIMIT 10;
```

**Query 4: Opportunities by score threshold**
```sql
SELECT * FROM opportunities
WHERE score >= 70
  AND is_actionable = true
  AND analyzed_at >= NOW() - INTERVAL '7 days'
ORDER BY score DESC;
```

**Query 5: Semantic similarity (vector search)**
```sql
SELECT id, event_id, score,
       1 - (embedding <=> '[query_embedding]') AS similarity
FROM opportunities
WHERE is_actionable = true
ORDER BY embedding <=> '[query_embedding]'
LIMIT 5;
```

### 8.2 Cron Schedule for AI Analysis

| Job | Frequency | Trigger | Action |
|-----|-----------|---------|--------|
| Raw data fetch | Every 15 min | OpenClaw cron / AWS EventBridge | Fetch sources → write S3 → write DynamoDB |
| Batch AI analysis | Every 30 min | OpenClaw cron | Fetch unanalyzed events → score → write Supabase |
| High-severity immediate analysis | DynamoDB Streams | Lambda trigger | Score severity ≥ 8 events immediately |
| Daily digest generation | Daily 08:00 CST | OpenClaw cron | Generate digest → write Supabase → Slack |
| Weekly digest generation | Every Monday 08:00 CST | OpenClaw cron | Generate digest → write Supabase → Slack |
| Telegram high-value push | Real-time | Supabase trigger (score ≥ 70) | Supabase webhook → Telegram Bot API |

### 8.3 OpenClaw Tool Definition

```json
{
  "name": "trendradar_query",
  "description": "Query TrendRadar analyzed opportunities from Supabase. Use for trend analysis, opportunity research, and competitive landscape queries.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query_type": {
        "type": "string",
        "enum": ["high_value", "by_category", "by_keyword", "by_score_threshold", "semantic", "summary"],
        "description": "Type of query to run"
      },
      "days": {
        "type": "integer",
        "default": 7,
        "description": "Look back period in days"
      },
      "category": {
        "type": "string",
        "description": "Opportunity type filter (fast_follow, innovation, infrastructure, meta_tool)"
      },
      "keyword": {
        "type": "string",
        "description": "Keyword to search in reasoning and pain_points"
      },
      "min_score": {
        "type": "integer",
        "description": "Minimum score threshold (0-100)"
      },
      "limit": {
        "type": "integer",
        "default": 10,
        "description": "Maximum number of results"
      }
    }
  }
}
```

---

## 9. Push Layer Design

### 9.1 Telegram Push (Instant Alerts)

**Trigger:** `score >= 70` AND `is_actionable = true` on any newly analyzed opportunity

**Format:** Telegram message with markdown

```
🔥 HIGH-VALUE OPPORTUNITY (Score: 78)

[Startup/Product Name]
Type: fast_follow | Difficulty: easy

💡 What's the pain?
• [Pain point 1]
• [Pain point 2]

🤖 AI Reasoning:
[2-3 sentence reasoning about why this is a good opportunity]

🛠 Suggested Action:
[Concrete next step]

📊 Score Breakdown:
Pain Density: 85 | Tech Feasibility: 70 | Timing: 75

🔗 Sources:
• PH: [url]
• HN: [url]
• VC: [url]

⏱ Analyzed: 2026-04-22 14:35 UTC
#opportunity #[category]
```

**Implementation:**
- Supabase `INSERT` trigger on `opportunities` table
- Trigger calls a webhook Lambda function
- Lambda calls Telegram Bot API `sendMessage`

### 9.2 Daily Digest (Slack — existing, enhanced)

**Trigger:** Daily at 08:00 CST

**Content:**
- Top 5 opportunities (score ≥ 60)
- Top 3 emerging pain points
- New YC batch highlights
- VC funding concentration map (top sectors)
- Week-over-week trend comparison

**Format:** Enhanced Slack Block Kit (existing format extended with opportunity data)

### 9.3 Weekly Digest (Slack — existing, enhanced)

**Trigger:** Every Monday at 08:00 CST

**Content:**
- Top 15 opportunities (score ≥ 55)
- Full pain point analysis
- Imitation difficulty distribution
- Opportunities by category (pie chart)
- Recommended focus area for the week

---

## 10. Development Phases

### Phase 1: Foundation (Weeks 1-3)
**Goal:** Core infrastructure — S3 + DynamoDB + basic event pipeline

#### Tasks:
1. [ ] Set up AWS account and configure IAM credentials locally
2. [ ] Create S3 bucket `s3://trendradar-raw` with lifecycle policy (Glacier after 90d, delete after 365d)
3. [ ] Create DynamoDB tables (`events`, `event_sources`) via CDK or AWS Console
4. [ ] Configure DynamoDB streams on `events` table
5. [ ] Set up AWS Lambda for S3 → DynamoDB ingestion pipeline
6. [ ] Modify existing source fetchers (`sources/`) to write raw JSON to S3 before processing
7. [ ] Add S3 write step to `sources/yc.py`, `sources/producthunt.py`, `sources/hackernews.py`, `sources/vc_funding.py`
8. [ ] Write Lambda function: S3 event trigger → read JSON → normalize → write to DynamoDB `events`
9. [ ] Set up DynamoDB GSI indexes (is_analyzed-index, event_id-index)
10. [ ] Create `event_sources` records linking raw signals to events
11. [ ] Write basic embedding generation step (OpenAI `text-embedding-3-small`, store in DynamoDB)
12. [ ] Write local test script to verify full S3 → DynamoDB pipeline
13. [ ] Document S3 path conventions and DynamoDB key schema in `docs/ARCHITECTURE.md`
14. [ ] Set up AWS credentials in OpenClaw environment variables

**Definition of Done:**
- All 4 existing sources write to S3 on each cron run
- DynamoDB `events` table contains deduplicated events with embeddings
- Lambda ingestion pipeline works reliably

---

### Phase 2: AI Analysis Engine (Weeks 4-6)
**Goal:** AI deduplication, scoring, and opportunity judgment pipeline

#### Tasks:
1. [ ] Set up Supabase project (use existing `sedwocbnyneberhsuhdr.supabase.co`)
2. [ ] Create `opportunities` table with DDL from Section 5.3
3. [ ] Enable `pgvector` extension for similarity search
4. [ ] Create vector embedding index on `opportunities.embedding`
5. [ ] Write OpenClaw Agent task: fetch unanalyzed events from DynamoDB
6. [ ] Implement dedup logic: embedding similarity search via Supabase IVFFlat
7. [ ] Implement scoring pipeline (pain_density, tech_feasibility, timing formulas)
8. [ ] Implement opportunity type classification (fast_follow, innovation, infrastructure, meta_tool)
9. [ ] Implement imitation_difficulty assignment
10. [ ] Write results to Supabase `opportunities` table
11. [ ] Configure DynamoDB Streams Lambda trigger for high-severity immediate analysis
12. [ ] Set up cron job: every 30 min run batch analysis on unanalyzed events
13. [ ] Write test cases for scoring logic (unit tests with mocked event data)
14. [ ] Implement `reasoning` field generation (LLM call to explain score)
15. [ ] Implement `references` field population from source data
16. [ ] Write `suggested_action` generation prompt (what to do next)

**Definition of Done:**
- AI analysis pipeline processes events automatically
- Supabase `opportunities` table is populated with scored, reasoned opportunities
- Score breakdown, reasoning, and references are all populated

---

### Phase 3: Data Source Expansion (Weeks 7-9)
**Goal:** Add 11 new data sources to feed the pipeline

#### Tasks:
1. [ ] Set up MCP connection for `playwright-mcp` in OpenClaw
2. [ ] Write Reddit scraper (r/startups, r/SaaS, r/indiehackers) via `playwright-mcp`
3. [ ] Write GitHub Trending scraper via `playwright-mcp`
4. [ ] Write RSS parser for 8 newsletter sources (feedparser)
5. [ ] Integrate HN MCP (existing via `playwright-mcp`)
6. [ ] Write Twitter/X keyword scraper or integrate third-party API
7. [ ] Write LinkedIn industry posts scraper (playwright, rate-limited)
8. [ ] Write AppSumo deals scraper
9. [ ] Write G2 / TrustRadius scrapers
10. [ ] Write competitor pricing page scraper (respect robots.txt)
11. [ ] Write generic web search via SearXNG MCP for ad-hoc queries
12. [ ] Integrate all new sources into S3 → DynamoDB pipeline
13. [ ] Add `source` field to DynamoDB records for all new sources
14. [ ] Write deduplication tests for cross-source dedup (e.g., same startup mentioned on Reddit AND PH)
15. [ ] Performance test: ensure all sources can be fetched within 15-min cron window (parallelize if needed)
16. [ ] Add source-specific embedding normalization (different sources may have different text lengths)

**Definition of Done:**
- 15 total data sources operational
- All sources write to S3 and flow to DynamoDB
- Cross-source deduplication works

---

### Phase 4: Delivery & Polish (Weeks 10-12)
**Goal:** Push notifications, OpenClaw agent integration, digest delivery, production hardening

#### Tasks:
1. [ ] Create Telegram Bot via @BotFather
2. [ ] Write Supabase webhook Lambda for opportunity push (score ≥ 70 → Telegram)
3. [ ] Configure Supabase INSERT trigger on `opportunities` table
4. [ ] Set up Telegram group/channel for push delivery
5. [ ] Enhance Slack digest with opportunity data (top N opportunities, score breakdown)
6. [ ] Implement OpenClaw `trendradar_query` tool (Section 8.3)
7. [ ] Write OpenClaw system prompt for TrendRadar agent (Section 7.5)
8. [ ] Test natural language queries: "What's hot in AI legal tools?"
9. [ ] Implement `trendradar_summary` query for daily briefing
10. [ ] Set up daily cron (08:00 CST) for digest generation and Slack push
11. [ ] Set up weekly cron (Monday 08:00 CST) for weekly digest
12. [ ] Implement rate limiting on Telegram push (max 5 per day to avoid spam)
13. [ ] Add `status` field workflow: new → reviewing → validated → building
14. [ ] Write user guide for Kaige: how to use OpenClaw queries + interpret scores
15. [ ] Production hardening: error handling, retry logic, dead letter queues
16. [ ] Cost estimation: S3, DynamoDB, Lambda, Supabase, OpenAI embedding calls
17. [ ] Set up CloudWatch dashboards for pipeline monitoring

**Definition of Done:**
- Telegram push working for high-value opportunities
- OpenClaw agent can answer natural language queries about opportunities
- Daily and weekly digests delivered to Slack
- Full end-to-end pipeline operational

---

## 11. Risk and Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Source API blocking** (PH, Twitter rate-limit or block scraping) | High | Medium | Implement exponential backoff; rotate user agents; use official APIs where available; fall back to RSS/news sources |
| **OpenAI embedding cost** (high volume of events → expensive) | High | Medium | Use `text-embedding-3-small` (cheap); batch embedding requests; reduce embedding dim to 256 for storage efficiency; cache embeddings |
| **DynamoDB hot partitions** (PK = `event_type#date` may be skewed) | Medium | Medium | Use write sharding on PK (append random suffix); monitor RCU/WCU; switch to on-demand billing |
| **Supabase pgvector performance** (large ANN index with many updates) | Medium | Medium | Partition by month; vacuum regularly; use `pgvector` 0.5+ with HNSW for faster approximate search |
| **MCP reliability** (playwright-mcp instability) | Medium | Low | Use HN Firebase API directly as fallback; wrap MCP calls with retry logic |
| **Telegram push spam** (too many high-score opportunities) | Low | Low | Rate limit: max 5 pushes/day; require score ≥ 75 for Telegram push (stricter than 70 threshold) |
| **Cron job overlap** (previous run not finished when next starts) | Low | Medium | Use DynamoDB conditional writes or Redis distributed lock; skip run if previous still running |
| **Data freshness** (15-min refresh not fast enough for viral trends) | Low | High | Add DynamoDB Streams trigger for immediate analysis of severity ≥ 8 events; combine with faster HN/Reddit polling |
| **Supabase connection limits** | Low | Low | Use connection pooling (Supabase's built-in PgBouncer); implement query result caching in OpenClaw |
| **GitHub push before Kaige approval** (red line) | N/A | Critical | Hard rule: no `git push` without explicit Kaige approval; CI/CD pipeline must require approval gate |
| **F-1/OPT self-employment constraint** | Contextual | High | All commercial activities go through Kaige's approval; no revenue-generating features without legal review |
| **YC API breaking changes** | Low | Low | Parse fallback HTML scraping already implemented; monitor API stability |

---

## Appendix A: Existing Code Reference

### Current Source Structure (`~/Projects/TrendRadar/sources/`)
| File | Description |
|------|-------------|
| `yc.py` | YC API fetch + HTML scraping fallback |
| `producthunt.py` | PH API/scraping |
| `hackernews.py` | HN Firebase API + keyword categorization |
| `vc_funding.py` | VC funding data fetch |

### Current Storage Structure (`~/Projects/TrendRadar/storage/`)
| File | Description |
|------|-------------|
| `trends.py` | JSON file storage + Supabase delegation |
| `supabase_client.py` | Supabase client with snapshots, digests, trend_history tables |

### Current Analyzer Structure (`~/Projects/TrendRadar/analyzer/`)
| File | Description |
|------|-------------|
| `trends.py` | Heuristic + LLM trend analysis, cross-source categorization |
| `digest.py` | Daily/weekly digest generation with Slack formatting |

### Existing Supabase Tables (to be preserved)
- `snapshots` — raw source snapshots
- `digests` — generated digests
- `trend_history` — time-series metrics

---

## Appendix B: DynamoDB Key Schema Reference

```
PK format: "{event_type}#{first_seen_date}"
SK format: "{event_id}"

Examples:
- PK: "startup_launch#2026-04-22"
- PK: "funding_round#2026-04-21"
- SK: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

Full record key:
  PK = "startup_launch#2026-04-22"
  SK = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

---

## Appendix C: Score Interpretation Guide

| Score Range | Label | Interpretation | Action |
|-------------|-------|----------------|--------|
| 80-100 | 🔥 Very High | Pain is acute, tech is simple, timing is perfect | Investigate immediately; consider starting today |
| 70-79 | ✅ High | Strong signal across most dimensions | Add to review queue; validate with community |
| 55-69 | 🟡 Medium | Good signal but some weaknesses | Monitor; wait for more data |
| 40-54 | 🟠 Low | Weak signal or hard to execute | Archive; check in 30 days |
| 0-39 | ⚪ Ignore | Not actionable for solo founder | Skip |

---

*Document Version: 2.0 | Last Updated: 2026-04-22*
