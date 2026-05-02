"""Exa Pain Signal Search — semantic search for pain signals across the web.

Uses Exa's semantic search to find pain signals that keyword matching misses.
Searches for frustration, unmet needs, and tool-seeking behavior.
"""

import os
import json
import requests
from datetime import datetime

EXA_API_URL = "https://api.exa.ai/search"
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")

# Pain search queries — semantic, not keyword-based
PAIN_QUERIES = [
    "what do professionals struggle with in their daily workflow",
    "biggest pain point in this industry right now",
    "frustrated with existing tools and looking for alternatives",
    "wasting hours on manual processes that should be automated",
    "the biggest problem nobody is solving in tech",
    "why is this process still so broken and slow",
    "desperately need a better solution for",
    "cancelled subscription because of",
    "migrated away from because it was too slow",
    "anyone know a better alternative to",
]

# Industry-specific queries
INDUSTRY_QUERIES = [
    "pain points in legal technology and compliance",
    "struggles in healthcare administration and billing",
    "frustration in financial reporting and accounting tools",
    "problems in developer tools and DevOps workflow",
    "challenges in sales and CRM systems",
    "issues with project management and collaboration tools",
    "difficulties in data analysis and business intelligence",
    "struggles in marketing automation and analytics",
]


def search_pain_signals(query: str, limit: int = 3) -> list[dict]:
    """Search for pain signals using Exa semantic search.
    
    Args:
        query: Search query (semantic, not keyword)
        limit: Max results per query
    
    Returns:
        List of {title, url, snippet, source}
    """
    if not EXA_API_KEY:
        return []
    
    try:
        resp = requests.post(
            EXA_API_URL,
            headers={
                "x-api-key": EXA_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "num_results": limit,
                "type": "auto",
                "contents": {"text": {"maxCharacters": 300}},
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for r in data.get("results", [])[:limit]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": (r.get("text", "") or "")[:300],
                "source": "exa_pain",
                "published": r.get("publishedDate"),
            })
        return results
    except Exception as e:
        print(f"Exa search error: {e}")
        return []


def fetch_all_pain_signals(queries: list[str] = None, limit_per_query: int = 3) -> list[dict]:
    """Fetch pain signals from multiple semantic queries.
    
    Args:
        queries: List of search queries (default: PAIN_QUERIES + INDUSTRY_QUERIES)
        limit_per_query: Max results per query
    
    Returns:
        Deduplicated list of pain signals
    """
    if queries is None:
        queries = PAIN_QUERIES + INDUSTRY_QUERIES
    
    all_signals = []
    seen_urls = set()
    
    for query in queries:
        results = search_pain_signals(query, limit=limit_per_query)
        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_signals.append(r)
    
    return all_signals


if __name__ == "__main__":
    print("Testing Exa pain search...")
    signals = fetch_all_pain_signals(queries=["what do developers struggle with"], limit_per_query=3)
    print(f"Found {len(signals)} signals")
    for s in signals[:5]:
        print(f"  {s['title'][:60]}...")
        print(f"  {s['url'][:60]}")
        print()
