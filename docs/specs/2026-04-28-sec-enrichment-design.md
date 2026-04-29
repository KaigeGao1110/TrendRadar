# SEC Company Enrichment — Design Spec (v2)

**Date:** 2026-04-28
**Status:** Approved
**Author:** Kaige + OpenClaw

---

## Goal

Enrich SEC Form D filings with company descriptions, sectors, and main business info.

## Data Summary

- Total SEC Form D records: 2,947
- After industry filter: 1,823
- After company dedup: **1,690 unique companies**
- Cost: $0 (DuckDuckGo free + OpenRouter free model)
- Time: ~2.5 hours (background subagent)

---

## Phase 1: Industry Filter

### Skip List (不关注)

| Industry | Records | Reason |
|----------|---------|--------|
| Commercial | 318 | 商业地产 |
| Other Real Estate | 352 | 房地产 |
| Residential | 171 | 住宅地产 |
| REITS and Finance | 51 | REIT |
| Insurance | 23 | 保险 |
| Other Banking and Financial Services | 71 | 银行/金融 |
| Oil and Gas | 53 | 能源 |
| Coal Mining | 1 | 矿业 |
| Lodging and Conventions | 2 | 酒店 |
| Agriculture | 10 | 农业 |
| Environmental Services | 7 | 环保 |
| Restaurants | 30 | 餐饮 |
| Retailing | 29 | 零售 |
| Investment Banking | 4 | 投行 |
| Tourism and Travel Services / Other Travel | 2 | 旅游 |

**Total skipped: 1,124**

### Keep Everything Else

包括 "Other"（574 条）也要查，LLM 自行判断赛道。

---

## Phase 2: Company Name Deduplication

### Rules

1. Normalize: uppercase, strip whitespace
2. Remove suffixes: Holdings Corp., Inc., LLC, L.P., Ltd., Co., Company
3. Match by normalized name → only enrich once per unique company
4. Store mapping: `normalized_name → [accession_numbers]`

### Example

```
"X.AI Holdings Corp." → "X.AI" (3 filings → enrich once)
"Nomadar Corp." → "NOMADAR" (1 filing → enrich once)
```

---

## Phase 3: Web Enrichment Pipeline

### For each unique company:

**Step 1: Search**
```
Query: "{cleaned_company_name} company what does it do"
Engine: DuckDuckGo (via web_fetch, free, unlimited)
Get: top 3 results
```

**Step 2: Fetch**
```
Pick: most relevant URL (company website > Crunchbase > LinkedIn > other)
Tool: web_fetch
Extract: raw text
```

**Step 3: LLM Extraction**
```
Model: openai/gpt-oss-120b:free (via OpenRouter, $0)
Prompt:
  Given this text about "{company_name}", extract:
  1. description: one sentence describing what the company does
  2. sector: classify into one of these sectors (or create a new one if none fit):
     AI/ML, Fintech, HealthTech, BioTech, EdTech, DevOps/Infra, Cybersecurity,
     E-commerce, SaaS, ClimateTech, AgTech, Robotics, Autonomous, Gaming, Media,
     RealEstateTech, LegalTech, HRTech, FoodTech, SpaceTech, Defense,
     Blockchain/Web3, Hardware, Semiconductor, Biopharma, MedicalDevices,
     InsurTech, ConstructionTech, Logistics, Finance, Energy, Other
  3. main_business: what they actually sell/build/do
  4. website: their homepage URL (if found)
  
  Return JSON: {"description": "...", "sector": "...", "main_business": "...", "website": "..."}
  
  If you cannot determine any field, set it to null.
```

### Company Name Cleaning for Search

```python
def clean_for_search(name):
    # Remove: Holdings, Corp, Inc, LLC, L.P., Ltd, Co, Company, etc.
    # Remove: punctuation
    # Keep: the distinctive part
    # "X.AI Holdings Corp." → "X.AI"
    # "Deep Cogito Inc." → "Deep Cogito"
    # "Bancar Technologies Ltd" → "Bancar Technologies"
```

---

## Phase 4: Database Schema

### Table: `sec_company_profiles`

```sql
CREATE TABLE IF NOT EXISTS sec_company_profiles (
  id SERIAL PRIMARY KEY,
  normalized_name TEXT NOT NULL UNIQUE,    -- dedup key
  entity_name TEXT NOT NULL,               -- original name
  
  -- Enriched fields
  description TEXT,                         -- 一句话描述
  sector TEXT,                              -- 细分赛道 (LLM 自由分类)
  main_business TEXT,                       -- 主营业务
  website TEXT,                             -- 公司官网
  
  -- Metadata
  accession_numbers TEXT[],                 -- all related filings
  enrichment_source TEXT,                   -- duckduckgo, crunchbase, etc.
  enrichment_quality TEXT,                  -- high/medium/low
  enriched_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sec_profiles_sector ON sec_company_profiles(sector);
CREATE INDEX idx_sec_profiles_name ON sec_company_profiles(normalized_name);
```

### Link Strategy

Use `normalized_name` as join key (not accession_number), since one company can have multiple filings.

```sql
-- Get enriched funding data
SELECT f.entity_name, f.total_offering_amount, f.date_of_first_sale,
       p.sector, p.description, p.main_business
FROM sec_form_d_filings f
LEFT JOIN sec_company_profiles p 
  ON UPPER(TRIM(f.entity_name)) = p.normalized_name
WHERE f.industry_group NOT IN (...)
ORDER BY f.total_offering_amount DESC;
```

---

## Phase 5: Sector Taxonomy

**Let LLM classify freely first.** After ~500 enrichments, review and consolidate:

1. LLM picks from predefined list OR creates new sector
2. After enough data, merge similar sectors (e.g., "HealthTech" + "MedicalDevices" → "HealthTech")
3. Update sector taxonomy in this doc

Predefined sectors (suggestions, not mandatory):
```
AI/ML, Fintech, HealthTech, BioTech, EdTech, DevOps/Infra, Cybersecurity,
E-commerce, SaaS, ClimateTech, AgTech, Robotics, Autonomous, Gaming, Media,
RealEstateTech, LegalTech, HRTech, FoodTech, SpaceTech, Defense,
Blockchain/Web3, Hardware, Semiconductor, Biopharma, MedicalDevices,
InsurTech, ConstructionTech, Logistics, Finance, Energy, Manufacturing, Other
```

---

## Phase 6: Pipeline & Cron

### Execution Model

**Background subagent** (not cron):
- Spawn a subagent to run enrichment
- It processes all 1,690 companies sequentially
- Reports progress every 100 companies
- Total time: ~2.5 hours
- Announces when done

### Daily Incremental (cron)

After SEC daily fetch (09:00):
```
09:30 CT → enrich new filings
  1. Query sec_form_d_filings WHERE accession_number NOT IN sec_company_profiles
  2. Filter by industry (skip list)
  3. Deduplicate by normalized_name (skip already enriched)
  4. For each new company: search → fetch → extract → upsert
```

### Re-enrichment (weekly)

```
Sunday 10:00 CT → re-enrich oldest 100 profiles
  1. Query sec_company_profiles ORDER BY enriched_at ASC LIMIT 100
  2. Re-run enrichment pipeline
  3. Update profiles (sector might change as LLM learns)
```

---

## Execution Plan

1. Create Supabase table `sec_company_profiles`
2. Create `sources/sec_enrichment.py` — web search + fetch + LLM extract
3. Create `analyzer/funding/sec_enrich.py` — orchestrator
4. Run bulk enrichment as subagent (1,690 companies)
5. Set up daily cron for incremental enrichment
6. Weekly re-enrichment cron (optional, add later)

---

## Open Questions

1. **OpenRouter API key** — Need to verify `openai/gpt-oss-120b:free` is available
2. **web_fetch rate limits** — DuckDuckGo might block if too fast
3. **Sector consolidation** — After first batch, review and merge
