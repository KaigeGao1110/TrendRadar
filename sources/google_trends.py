"""Google Trends Fetcher — fetches daily trending searches via pytrends.

Provides timing dimension — what topics are gaining search momentum right now.
Requires: pytrends (pip install pytrends)
"""

from datetime import datetime

REQUEST_TIMEOUT = 30


def _check_pytrends():
    """Lazy import pytrends with helpful error message."""
    try:
        from pytrends.request import TrendReq
        return TrendReq
    except ImportError:
        raise ImportError(
            "pytrends is required. Install with: .venv/bin/pip install pytrends"
        )


def fetch_trending_searches() -> list[dict]:
    """Fetch today's trending searches from Google Trends.

    Returns:
        List of dicts with trending search queries.
    """
    TrendReq = _check_pytrends()
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=REQUEST_TIMEOUT)
        df = pytrends.trending_searches(pn="united_states")
        results = []
        for _, row in df.iterrows():
            query = str(row.iloc[0]) if len(row) > 0 else ""
            if not query:
                continue
            results.append({
                "title": query,
                "url": f"https://trends.google.com/trends/explore?q={query}",
                "source": "google_trends",
                "description": f"Google Trends daily trending search: {query}",
                "industry": ["trending"],
                "published_at": datetime.utcnow().isoformat() + "Z",
                "metadata": {
                    "query": query,
                    "type": "daily_trending",
                },
            })
        return results
    except Exception as e:
        print(f"⚠️ Google Trends trending_searches failed: {e}")
        return []


def fetch_related_queries(keyword: str = "startup") -> list[dict]:
    """Fetch related queries for a keyword from Google Trends.

    Args:
        keyword: Search term to find related queries for.

    Returns:
        List of dicts with related query information.
    """
    TrendReq = _check_pytrends()
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=REQUEST_TIMEOUT)
        pytrends.build_payload([keyword], cat=0, timeframe="today 3-m")
        related = pytrends.related_queries()

        results = []
        keyword_data = related.get(keyword, {})
        
        # Top related queries
        top_df = keyword_data.get("top")
        if top_df is not None and not top_df.empty:
            for _, row in top_df.iterrows():
                query = str(row.get("query", ""))
                value = row.get("value", 0)
                if not query:
                    continue
                try:
                    value = int(value) if value else 0
                except (ValueError, TypeError):
                    value = 0
                results.append({
                    "title": query,
                    "url": f"https://trends.google.com/trends/explore?q={query}",
                    "source": "google_trends",
                    "description": f"Related to '{keyword}' — search volume: {value}",
                    "industry": ["trending"],
                    "published_at": datetime.utcnow().isoformat() + "Z",
                    "metadata": {
                        "query": query,
                        "trend_volume": value,
                        "related_to": keyword,
                        "type": "related_top",
                    },
                })

        # Rising related queries
        rising_df = keyword_data.get("rising")
        if rising_df is not None and not rising_df.empty:
            for _, row in rising_df.iterrows():
                query = str(row.get("query", ""))
                value = str(row.get("value", ""))
                if not query:
                    continue
                results.append({
                    "title": query,
                    "url": f"https://trends.google.com/trends/explore?q={query}",
                    "source": "google_trends",
                    "description": f"Rising query related to '{keyword}' — {value}",
                    "industry": ["trending"],
                    "published_at": datetime.utcnow().isoformat() + "Z",
                    "metadata": {
                        "query": query,
                        "trend_volume": value,
                        "related_to": keyword,
                        "type": "related_rising",
                    },
                })

        return results
    except Exception as e:
        print(f"⚠️ Google Trends related_queries failed for '{keyword}': {e}")
        return []


def fetch_latest() -> list[dict]:
    """Fetch trending searches and related queries for key startup terms.

    Returns:
        List of dicts with title, url, source, description, industry,
        published_at, metadata.
    """
    all_results = []

    # Daily trending searches
    trending = fetch_trending_searches()
    all_results.extend(trending)

    # Related queries for key terms
    keywords = ["startup", "SaaS", "AI tool"]
    for kw in keywords:
        related = fetch_related_queries(kw)
        all_results.extend(related)

    # Deduplicate by query
    seen = set()
    unique = []
    for item in all_results:
        query = item.get("metadata", {}).get("query", "")
        if query and query not in seen:
            seen.add(query)
            unique.append(item)

    return unique[:50]


if __name__ == "__main__":
    items = fetch_latest()
    print(f"Fetched {len(items)} Google Trends items\n")
    for item in items[:10]:
        meta = item.get("metadata", {})
        print(f"📈 [{meta.get('type', '?')}] {item['title']}")
        print(f"   {item['description'][:80]}")
        print()
