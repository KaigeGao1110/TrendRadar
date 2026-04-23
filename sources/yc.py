"""YC Batch Scraper — fetches companies from Y Combinator."""

import requests
from datetime import datetime

YC_API_URL = "https://api.ycombinator.com/v0.1/companies"


def fetch_latest_batch(batch_name: str = None) -> list[dict]:
    """Fetch companies from a YC batch.

    Uses YC's public API endpoint.

    Args:
        batch_name: e.g. "W24", "S25". If None, fetches latest batch.

    Returns:
        [{name, one_liner, batch, industry, tags[], url}]
    """
    try:
        # YC's public API returns all companies
        response = requests.get(
            YC_API_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )

        if response.status_code == 200:
            raw = response.json()
            # API returns {"companies": [...]} not a list directly
            data = raw.get("companies", raw) if isinstance(raw, dict) else raw
            companies = []

            # Determine latest batch if not specified
            all_batches = set()
            for company in data:
                batch = company.get("batch", "")
                if batch:
                    all_batches.add(batch)

            if batch_name is None and all_batches:
                # Sort batches to find latest (W > S for same year, newest year first)
                def batch_sort_key(b):
                    year = int(b[1:]) if len(b) > 1 and b[1:].isdigit() else 0
                    season = 0 if b[0] == "W" else 1  # W before S
                    return (-year, season)
                batch_name = sorted(all_batches, key=batch_sort_key)[0]

            for company in data:
                batch = company.get("batch", "")
                if batch_name and batch != batch_name:
                    continue

                companies.append({
                    "name": company.get("name", ""),
                    "one_liner": company.get("oneLiner", company.get("one_liner", "")),
                    "batch": batch,
                    "industry": company.get("industries", []),
                    "tags": company.get("tags", []),
                    "url": company.get("url", f"https://www.ycombinator.com/companies/{company.get('slug', '')}"),
                    "team_size": company.get("teamSize", company.get("team_size", 0)),
                    "status": company.get("status", ""),
                })

            if companies:
                return companies
    except Exception:
        pass

    # Fallback: scrape YC directory page
    return _scrape_yc_directory(batch_name)


def _scrape_yc_directory(batch_name: str = None) -> list[dict]:
    """Scrape YC directory page as fallback."""
    try:
        url = "https://www.ycombinator.com/companies"
        params = {}
        if batch_name:
            params["batch"] = batch_name

        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0 Chrome/120"},
            timeout=15,
        )

        if response.status_code == 200:
            import json
            import re

            companies = []
            # YC embeds company data in JSON within the page
            for match in re.finditer(r'"companies"\s*:\s*(\[.*?\])', response.text, re.DOTALL):
                try:
                    raw_companies = json.loads(match.group(1))
                    for c in raw_companies:
                        companies.append({
                            "name": c.get("name", ""),
                            "one_liner": c.get("one_liner", c.get("tagline", "")),
                            "batch": c.get("batch", ""),
                            "industry": c.get("industries", []),
                            "tags": c.get("tags", []),
                            "url": f"https://www.ycombinator.com/companies/{c.get('slug', '')}",
                            "team_size": c.get("team_size", 0),
                            "status": c.get("status", ""),
                        })
                    if companies:
                        return companies[:100]
                except (json.JSONDecodeError, Exception):
                    continue

            # Alternative: look for Next.js data
            for match in re.finditer(r'__NEXT_DATA__[^>]*>(.*?)</script>', response.text, re.DOTALL):
                try:
                    next_data = json.loads(match.group(1))
                    props = next_data.get("props", {}).get("pageProps", {})
                    raw = props.get("companies", props.get("results", []))
                    if isinstance(raw, list):
                        for c in raw:
                            companies.append({
                                "name": c.get("name", ""),
                                "one_liner": c.get("one_liner", c.get("tagline", "")),
                                "batch": c.get("batch_name", c.get("batch", "")),
                                "industry": c.get("industries", []),
                                "tags": c.get("tags", []),
                                "url": f"https://www.ycombinator.com/companies/{c.get('slug', '')}",
                                "team_size": c.get("team_size", 0),
                                "status": c.get("status", ""),
                            })
                        if companies:
                            return companies[:100]
                except (json.JSONDecodeError, Exception):
                    continue
    except Exception:
        pass

    return []


def fetch_all_batches_since(year: int = 2024) -> list[dict]:
    """Fetch all companies from batches since a given year."""
    all_companies = fetch_latest_batch()  # This fetches all, filter by year
    return [
        c for c in all_companies
        if c.get("batch", "") and _batch_year(c["batch"]) >= year
    ]


def _batch_year(batch: str) -> int:
    """Extract year from batch string like 'W24' -> 2024."""
    if len(batch) >= 2 and batch[1:].isdigit():
        year = int(batch[1:])
        return 2000 + year if year < 100 else year
    return 0


def categorize_companies(companies: list[dict]) -> dict:
    """Group companies by category/industry and count."""
    categories: dict = {}

    for company in companies:
        industries = company.get("industry", [])
        if isinstance(industries, str):
            industries = [industries]
        if not industries:
            industries = ["Other"]

        for industry in industries:
            if industry and isinstance(industry, str):
                if industry not in categories:
                    categories[industry] = {"count": 0, "companies": [], "examples": []}
                categories[industry]["count"] += 1
                categories[industry]["companies"].append(company["name"])
                if len(categories[industry]["examples"]) < 3:
                    categories[industry]["examples"].append(
                        f"{company['name']}: {company.get('one_liner', '')[:60]}"
                    )

    return categories
