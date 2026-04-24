# FundBat Data Source
Free startup funding and valuation data for TrendRadar
https://fundbat.com

## Stats
- 791 companies tracked
- Weekly updates
- Data fields: name, funding amount, valuation, category, location, founded year, status, url

## Usage
```python
from sources.fundbat import fetch_all_companies
companies = fetch_all_companies(limit=100)  # Optional limit, default = all 791
```

## Data Sample
```python
{
    "name": "OpenAI",
    "funding_amount": "$167.9B",
    "valuation": "$840.0B",
    "category": "Artificial Intelligence  SaaS",
    "location": "San Francisco, US",
    "founded_year": "2015",
    "status": "Private",
    "url": "https://fundbat.com/company/openai",
    "source": "fundbat",
    "crawled_at": "2026-04-24T07:15:00Z"
}
```

## Dependencies
- Playwright + Chromium (installed in venv)
- No API keys required, free to scrape
- Rate limit: 1 full scrape per week
