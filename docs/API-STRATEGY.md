# TrendRadar API Strategy

**Version:** 1.0
**Date:** 2026-04-23
**Status:** Active

---

## Overview

TrendRadar uses multiple data sources with different pricing tiers, rate limits, and use cases. This document defines the **strategic layer** — when to use which API, in what order, and how to maximize value from limited quotas.

**Core Principle:** Free sources are the primary pipeline. Paid/limited APIs are verification and enrichment layers, not discovery layers.

---

## Data Sources Inventory

### Tier 1 — Unlimited Free (Primary Pipeline)

These are the workhorses. Use them for all discovery and routine data collection.

| Source | API Type | Rate Limit | Auth | Use Case |
|--------|----------|-----------|------|----------|
| Hacker News | Firebase | Unlimited | None | Tech community signals, pain points |
| GitHub Trending | REST API | 5,000 req/hr | OAuth (free) | Developer trends, repo growth |
| GitHub Events | REST API | Unlimited (public events) | None | Real-time activity signals |
| Y Combinator | Public API | Unlimited | None | Startup batch data, company listings |
| Dev.to | REST API | Unlimited | None | Developer articles, tech discussions |
| RSS Feeds | feedparser | Unlimited | None | Newsletter aggregation (Lenny's, TLDR, a16z, etc.) |
| Product Hunt | OAuth | Rate limited | OAuth app | Product launches, votes, comments |
| Reddit | OAuth | 100 req/min | Reddit app | Community pain points (r/startups, r/SaaS) |

### Tier 2 — Quota-Based (Secondary Verification)

Use strategically. Guard quotas. Cache aggressively.

| Source | Key | Quota | Guard Rule | Use Case |
|--------|-----|-------|-----------|----------|
| **Crustdata** | `275cb5e116e810d42d0b0ca65b895ce00224ceba` | Unknown (assume moderate) | Cache 7 days | Company info, funding rounds, team |
| **Crunchbase** (RapidAPI) | `59351167bemsh69cb04174744b16p1959cdjsn9e952846fbf3` | **20 req/month** | Cache 30 days, score ≥ 70 only | Official funding data, investor verification |
| **LinkedIn Scraper** (RapidAPI) | `59351167bemsh69cb04174744b16p1959cdjsn9e952846fbf3` | **50 credits/70 req/month** | ⚠️ DISABLED — service shut down; Cache N/A until reactivated | Discover similar companies/people from a LinkedIn profile URL |
| **NewsAPI.org** | Register: https://newsapi.org | 100 req/day | Cache 24 hours | News aggregation, trend monitoring |

### Tier 3 — Free Tier with Registration

Verify and register as needed.

| Source | Registration | Free Tier | Notes |
|--------|-------------|-----------|-------|
| Dealroom.co | https://dealroom.co/for-builders/ | Free for startups raised <$10M | 3M+ company profiles, funding data |
| FundBat | https://fundbat.com/ | Completely free | 791 companies, open source alternative to Crunchbase |
| Tracxn Lite | https://www.tracxn.com | Limited free discovery | Global coverage, deep sector insights |
| Koyfin | https://koyfin.com | Free public data | Public-to-private market connections |
| Apollo.io | https://apollo.io | 60 credits/month | B2B contact data, company verification |
| CourtListener | https://courtlistener.com | Completely free | US federal court cases, legal signals |
| FreeStartupFunding | https://freestartupfunding.com | Free | 7,884+ SEC-verified VC funds |

### LinkedIn Scraper (⚠️ DISABLED)

**Status (2026-04-24):** The `similar-profiles` endpoint returns `"We are no longer providing this service"`. The API is effectively dead until the provider re-enables it.

- **Quota remaining:** ~47 credits / 70 requests (per monthly reset)
- **Retry strategy:** Check monthly. If service returns, uncomment quota enforcement in `linkedin.py`.
- **Alternative:** Use Apollo.io (Tier 3) for company/people enrichment instead.

### Tier 4 — API Marketplace (Tool APIs)

Not data sources — utility tools for processing and enrichment.

| Source | Registration | Free Tier | Use Case |
|--------|-------------|-----------|----------|
| APyHub Startup Program | https://apyhub.com/startup | 200+ APIs free for startups | File processing, AI, data validation |
| APIKeyHub | https://apikeyhub.com | Directory only (3,109+ APIs) | Discovery of free APIs |
| Zyla API Hub | https://zylalabs.com | 7-day trial / 50 requests | Quick testing of paid APIs |

---

## Strategic Usage Rules

### Rule 1: Free Sources First

```
ALWAYS query free sources before touching quota-based APIs.

Order of operations:
1. Hacker News / Reddit / GitHub / YC (unlimited)
2. Dev.to / RSS feeds (unlimited)
3. Product Hunt / Reddit (rate limited but free)
4. Crustdata (moderate quota)
5. NewsAPI.org (daily quota)
6. Crunchbase (20/month — last resort)
```

### Rule 2: Cache Aggressively

```python
# Cache TTL by source
HN_CACHE_TTL = 15 * 60          # 15 minutes — real-time
GITHUB_CACHE_TTL = 60 * 60     # 1 hour — trending moves fast
CRUSTDATA_CACHE_TTL = 7 * 24 * 3600   # 7 days
NEWSAPI_CACHE_TTL = 24 * 3600   # 24 hours
CRUNCHBASE_CACHE_TTL = 30 * 24 * 3600  # 30 days — official data doesn't change daily
DEALROOM_CACHE_TTL = 7 * 24 * 3600     # 7 days
```

### Rule 3: Crunchbase is Verification, Not Discovery

```
DON'T use Crunchbase to find companies.
DO use Crunchbase to VERIFY high-confidence opportunities.

Trigger condition: opportunity score ≥ 70
Monthly budget: 20 requests = ~5 per week
```

### Rule 4: Three-Layer Architecture

```
Layer 1 — Discovery (Unlimited Free)
  Sources: HN, Reddit, GitHub, YC, Dev.to, RSS
  Purpose: Find signals, extract pain points, identify trends
  
Layer 2 — Enrichment (Quota-Based)
  Sources: Crustdata, NewsAPI, Dealroom
  Purpose: Add company context, news context, funding data
  
Layer 3 — Verification (20/month)
  Sources: Crunchbase
  Purpose: Confirm official funding data, investor names, valuation
```

### Rule 5: Guard Rate Limits in Code

```python
class RateLimitGuard:
    def __init__(self, name, max_calls, window_seconds):
        self.name = name
        self.max_calls = max_calls
        self.window = window_seconds
        self.calls = []
    
    def can_call(self):
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.window]
        return len(self.calls) < self.max_calls
    
    def record_call(self):
        self.calls.append(time.time())
    
    def assert_can_call(self):
        if not self.can_call():
            raise QuotaExhaustedError(
                f"{self.name} quota exhausted. "
                f"Wait {self.window}s or use cached data."
            )

# Usage
crunchbase_guard = RateLimitGuard("Crunchbase", max_calls=20, window_seconds=30*24*3600)
crunchbase_guard.assert_can_call()
crunchbase_guard.record_call()
```

---

## API Keys Reference

### Active Keys

| Service | Key | Quota | Stored In |
|---------|-----|-------|-----------|
| Crustdata | `275cb5e116e810d42d0b0ca65b895ce00224ceba` | Moderate | Environment / secrets manager |
| Crunchbase (RapidAPI) | `59351167bemsh69cb04174744b16p1959cdjsn9e952846fbf3` | 20/month | Environment / secrets manager |
| LinkedIn Scraper (RapidAPI) | `59351167bemsh69cb04174744b16p1959cdjsn9e952846fbf3` | 50 credits/70 req/month | Environment / secrets manager | ⚠️ DISABLED |
| Tavily | `$TAVILY_API_KEY` | 1,000/month | OpenClaw env |

### Registration Required

| Service | Registration URL | Free Tier |
|---------|-----------------|-----------|
| NewsAPI.org | https://newsapi.org/register | 100 req/day |
| Reddit API | https://www.reddit.com/prefs/apps | 100 req/min |
| Product Hunt | https://api.producthunt.com/v2/oauth/applications | Free OAuth |
| Dealroom.co | https://dealroom.co/for-builders/ | Free for startups <$10M |
| APyHub Startup | https://apyhub.com/startup | 200+ APIs free |

### No Key Required

| Service | Auth | URL/Method |
|---------|------|------------|
| Hacker News | None | Firebase API |
| GitHub REST | Optional OAuth | api.github.com |
| Y Combinator | None | api.ycombinator.com |
| Dev.to | None | dev.to/api |
| RSS Feeds | None | feedparser |
| FundBat | None | fundbat.com (web scraping) |
| CourtListener | Free API key | courtlistener.com |

---

## Source-Specific Strategies

### Hacker News (Primary Signal Source)

- **Role:** Real-time tech community pain points, startup launches
- **Strategy:** Poll top stories every 15 minutes via Firebase
- **Key endpoints:**
  - Top stories: `https://hacker-news.firebaseio.com/v0/topstories.json`
  - Story details: `https://hacker-news.firebaseio.com/v0/item/{id}.json`
- **Cache:** 15 minutes

### Reddit (Community Signals)

- **Role:** Unfiltered user complaints, market pain points
- **Strategy:** Monitor r/startups, r/SaaS, r/indiehackers
- **Auth:** OAuth 2.0 (reddit app)
- **Cache:** 30 minutes
- **Guard:** Stay under 100 req/min

### GitHub (Developer Trends)

- **Role:** Technology adoption signals, repo growth
- **Strategy:** Poll trending repos daily, watch star growth
- **Key:** Use GraphQL for complex queries (less requests)
- **Cache:** 1 hour for trending, 24 hours for detailed repo data

### Crustdata (Company Enrichment)

- **Role:** Company info, funding rounds, team size, location
- **Strategy:** Use after free sources identify interesting companies
- **Cache:** 7 days (company data doesn't change hourly)
- **Priority:** High-value enrichment before Crunchbase

### Crunchbase (Official Verification)

- **Role:** Final verification of funding data
- **Strategy:**
  ```
  Trigger: opportunity score ≥ 70 AND cache expired
  Monthly budget: 20 calls
  Weekly allocation: ~5 calls
  Guard: Always check cache before calling
  ```
- **Example call:**
  ```bash
  curl --request POST \
    --url https://crunchbase4.p.rapidapi.com/company \
    --header 'Content-Type: application/json' \
    --header 'x-rapidapi-host: crunchbase4.p.rapidapi.com' \
    --header 'x-rapidapi-key: $CRUNCHBASE_KEY' \
    --data '{"company_domain":"apple.com"}'
  ```

### NewsAPI (News Aggregation)

- **Role:** Monitor news coverage of companies, trends
- **Strategy:** Query by keyword, cache results
- **Guard:** 100 req/day — use for high-value news only
- **Cache:** 24 hours

### Dealroom.co (European/Startup Data)

- **Role:** Alternative to Crunchbase, European startup coverage
- **Strategy:** Free tier for startups — register as founder
- **Cache:** 7 days
- **Note:** 3M+ company profiles, better for discovery than Crunchbase

### FundBat (Open Source Crunchbase)

- **Role:** Free funding data, open alternative
- **Strategy:** Web scraping or API if available
- **Cache:** 24 hours (weekly updates)
- **Note:** 791 tracked companies, verified funding sources

---

## Decision Flowchart

```
New opportunity detected
         │
         ▼
Is it from free source? ──No──► Log and skip (only process free-source data)
         │
        Yes
         ▼
Does it meet score threshold? ──No──► Log and deprioritize
         │
        Yes (score ≥ 70)
         │
         ▼
Is it in Crustdata cache? ──No──► Call Crustdata → Cache 7 days
         │                              │
        Yes                             ▼
         ▼                      Is it high priority?
Is it in Crunchbase cache? ──No──►    (score ≥ 85)?
         │                              │
        Yes                             ▼
         ▼                        Call Crunchbase ──► Cache 30 days
Finalize opportunity                 │
and push to Telegram                  ▼
                                  Log for next cycle
```

---

## Cron Schedule Recommendations

| Time | Job | Sources | Priority |
|------|-----|---------|----------|
| Every 15 min | HN Top Stories | Hacker News API | P0 — free, real-time |
| Every 30 min | Reddit Signals | Reddit API | P0 — free, pain points |
| Every 1 hour | GitHub Trending | GitHub API | P1 — free, dev trends |
| Every 4 hours | Product Hunt | PH API | P1 — free, launches |
| Every 6 hours | YC Batch | YC API | P1 — free, startup data |
| Every 6 hours | News Monitor | NewsAPI | P2 — 100/day limit |
| Daily | Crustdata Enrichment | Crustdata | P2 — moderate quota |
| Weekly | Crunchbase Verification | Crunchbase | P3 — 20/month limit |
| Daily | RSS Digest | feedparser | P0 — free, newsletters |

---

## Quota Management

### Monthly Budget (20 Crunchbase calls)

```
Week 1: 5 calls (early validation)
Week 2: 5 calls (mid-cycle check)
Week 3: 5 calls (digest preparation)
Week 4: 5 calls (final verification)
```

### Daily Budget (100 NewsAPI calls)

```
Morning digest: 20 calls
Mid-day check: 20 calls
Evening summary: 20 calls
Reserve: 40 calls for breaking news
```

---

## Error Handling

```python
class APIError(Exception):
    pass

class QuotaExhaustedError(APIError):
    pass

class RateLimitError(APIError):
    pass

def call_with_fallback(primary_fn, fallback_fn, source_name):
    try:
        return primary_fn()
    except QuotaExhaustedError:
        logging.warning(f"{source_name} quota exhausted, using fallback")
        return fallback_fn()
    except RateLimitError:
        logging.warning(f"{source_name} rate limited, retrying in 60s")
        time.sleep(60)
        return primary_fn()
    except Exception as e:
        logging.error(f"{source_name} failed: {e}")
        return fallback_fn()
```

---

## Review and Update

- **Weekly:** Check quota usage, adjust caching TTLs
- **Monthly:** Review which sources are generating highest-value signals
- **Quarterly:** Re-evaluate API marketplace for new free tier opportunities

---

*Last updated: 2026-04-23*
