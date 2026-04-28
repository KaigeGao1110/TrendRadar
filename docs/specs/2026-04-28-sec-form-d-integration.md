# SEC Form D Integration — Design Spec

**Date:** 2026-04-28
**Status:** Approved
**Author:** Kaige + OpenClaw

---

## Goal

Replace FundBat as the primary funding data source with SEC EDGAR Form D, which has real funding dates (not just crawl timestamps).

## Data Source

**SEC EDGAR Form D** — Notices of Exempt Offerings filed with the SEC.
- **Legal requirement:** Every US company raising via private placement must file Form D
- **Fields available:** Company name, funding date (dateOfFirstSale), offering amount, industry group, SIC code, state, investor count, entity type
- **Free:** Government data, no API key needed
- **Real-time:** Filings appear on EDGAR immediately after submission

### Two Access Methods

| Method | Update | Use Case |
|--------|--------|----------|
| **EDGAR Full-Text Search API** | Real-time | Daily cron — fetch today's filings |
| **Quarterly ZIP bulk download** | Quarterly | Initial load + quarterly reconciliation |

### API Endpoint

```
GET https://efts.sec.gov/LATEST/search-index
  ?forms=D
  &dateRange=custom
  &startdt=YYYY-MM-DD
  &enddt=YYYY-MM-DD
  &hits.hits.total=true
  &size=100
  &from=0

Header: User-Agent: TrendRadar research@trendradar.ai
```

Response contains: `file_date`, `display_names`, `adsh` (accession number), `sics`, `biz_locations`

To get offering details (amount, date of first sale), fetch individual XML:
```
GET https://www.sec.gov/Archives/edgar/data/{CIK}/{accession_no_slashes}/primary_doc.xml
```

### ZIP Bulk Download

```
GET https://www.sec.gov/files/structureddata/data/form-d-data-sets/YYYYqQ_d.zip
```

Contains TSV files:
- `ISSUERS.tsv` — Company name, CIK, city, state, entity type, year of incorporation
- `OFFERING.tsv` — Industry group, sale date, offering amount, amount sold, investor count
- `FORMDSUBMISSION.tsv` — Filing date, SIC code, submission type

Join on `ACCESSIONNUMBER`.

---

## Architecture

### New Files

```
sources/
  sec_edgar.py          # EDGAR API client (search + XML fetch + parse)
  sec_edgar_bulk.py     # Quarterly ZIP download + TSV parser

analyzer/
  funding/
    sec_ingest.py       # Orchestrator: API daily fetch + bulk load → Supabase

supabase/
  migrations/
    sec_form_d.sql      # Table: sec_form_d_filings
```

### Supabase Table: `sec_form_d_filings`

```sql
CREATE TABLE IF NOT EXISTS sec_form_d_filings (
  accession_number TEXT PRIMARY KEY,
  entity_name TEXT NOT NULL,
  cik TEXT,
  filing_date DATE NOT NULL,
  date_of_first_sale DATE,
  total_offering_amount NUMERIC,
  total_amount_sold NUMERIC,
  total_remaining NUMERIC,
  industry_group TEXT,
  sic_code TEXT,
  entity_type TEXT,
  jurisdiction TEXT,
  city TEXT,
  state TEXT,
  investor_count INTEGER,
  is_amendment BOOLEAN DEFAULT FALSE,
  source TEXT DEFAULT 'sec_edgar',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sec_form_d_filing_date ON sec_form_d_filings(filing_date);
CREATE INDEX idx_sec_form_d_industry ON sec_form_d_filings(industry_group);
CREATE INDEX idx_sec_form_d_amount ON sec_form_d_filings(total_offering_amount);
CREATE INDEX idx_sec_form_d_entity ON sec_form_d_filings(entity_name);
```

### Filters

**Include:**
- Non-fund filings (exclude: Pooled Investment Fund, Private Equity Fund, Hedge Fund, Venture Capital Fund)
- Amount >= $1M (filter out tiny offerings)
- US companies only

**Industries of interest:**
- Other Technology
- Biotechnology
- Other Health Care
- Business Services
- Manufacturing
- (store all, but highlight these in reports)

### Cron Job

**Daily at 09:00 CT:**
1. Search EDGAR for Form D filings from yesterday
2. For each non-fund filing: fetch XML → parse offering details
3. Upsert into `sec_form_d_filings`
4. Generate summary: count, top deals, industry breakdown

**Quarterly (manual trigger or cron):**
1. Download latest ZIP from SEC.gov
2. Parse TSV files
3. Upsert into `sec_form_d_filings` (bulk load)

---

## Acceptance Criteria

1. [ ] `sec_edgar.py` can search Form D filings by date range
2. [ ] `sec_edgar.py` can parse XML to extract: entity_name, date_of_first_sale, total_offering_amount, industry_group, investor_count
3. [ ] `sec_edgar_bulk.py` can download and parse quarterly ZIP files
4. [ ] `sec_ingest.py` orchestrates daily fetch → parse → upsert
5. [ ] Supabase table `sec_form_d_filings` created
6. [ ] Data flows: EDGAR API → parse → Supabase
7. [ ] Cron job runs daily at 09:00 CT
8. [ ] FundBat remains as secondary source (for valuation data)
9. [ ] Initial bulk load from 2026 Q1 ZIP (4,250+ records)
