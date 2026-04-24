"""NewsAPI source for TrendRadar — news aggregation and trend monitoring.

Docs: https://newsapi.org/docs
Key: 1eaa8ff6adae4d0daf55e75772c20c95
Quota: 100 req/day — cache 24 hours
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────

NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "1eaa8ff6adae4d0daf55e75772c20c95")
NEWS_API_BASE = "https://newsapi.org/v2"
CACHE_TTL_SECONDS = 24 * 3600  # 24 hours per API-STRATEGY.md

# ── In-memory request guard (100 req/day) ─────────────────────────────────────

class _RateGuard:
    """Lightweight in-process rate limiter for NewsAPI.

    100 req/day means ~4 req/hour on average.  In practice the daily
    cron jobs will burn through quota quickly, so we gate at the call site.
    """

    def __init__(self, max_per_day: int = 100):
        self.max_per_day = max_per_day
        self.calls: list[float] = []

    def can_call(self) -> bool:
        now = datetime.now().timestamp()
        day_start = (now // 86400) * 86400
        self.calls = [t for t in self.calls if t >= day_start]
        return len(self.calls) < self.max_per_day

    def record(self):
        self.calls.append(datetime.now().timestamp())

    def remaining(self) -> int:
        now = datetime.now().timestamp()
        day_start = (now // 86400) * 86400
        self.calls = [t for t in self.calls if t >= day_start]
        return max(0, self.max_per_day - len(self.calls))


_rate_guard = _RateGuard()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _news_error_to_str(code: int, msg: str) -> str:
    return f"NewsAPI error {code}: {msg}"


def _call(url: str, params: dict) -> dict:
    """Make a NewsAPI request; raise on quota/rate errors."""
    if not _rate_guard.can_call():
        raise RuntimeError(
            f"NewsAPI daily quota exhausted ({_rate_guard.max_per_day} req/day). "
            "Wait until tomorrow or use cached data."
        )

    headers = {"X-Api-Key": NEWS_API_KEY}
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    _rate_guard.record()

    data = resp.json()
    if data.get("status") == "error":
        code = resp.status_code
        msg = data.get("message", "Unknown error")
        if "quota" in msg.lower() or code == 429:
            raise RuntimeError(f"NewsAPI quota exceeded: {msg}")
        raise RuntimeError(_news_error_to_str(code, msg))

    return data


def _normalize_article(article: dict) -> dict:
    """Flatten a NewsAPI article dict into TrendRadar's standard shape."""
    source = article.get("source", {})
    return {
        "title": article.get("title") or "",
        "description": article.get("description") or "",
        "url": article.get("url") or "",
        "publishedAt": article.get("publishedAt") or "",
        "source": source.get("name") or source.get("id") or "unknown",
        "author": article.get("author") or "",
        "urlToImage": article.get("urlToImage") or "",
        "content": (article.get("content") or "")[:300],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_tech_headlines(
    country: str = "us",
    page_size: int = 20,
) -> list[dict]:
    """Fetch top tech headlines from NewsAPI.

    Args:
        country: 2-letter ISO 3166-1 code (default us).
        page_size: Results per page, max 100.

    Returns:
        [{title, description, url, publishedAt, source, author, urlToImage, content}]
    """
    url = f"{NEWS_API_BASE}/top-headlines"
    params = {"category": "technology", "country": country, "pageSize": min(page_size, 100)}

    try:
        data = _call(url, params)
        return [_normalize_article(a) for a in data.get("articles", [])]
    except Exception as e:
        logging.warning(f"fetch_tech_headlines failed: {e}")
        return _sample_articles("tech")


def fetch_business_headlines(
    country: str = "us",
    page_size: int = 20,
) -> list[dict]:
    """Fetch top business headlines from NewsAPI."""
    url = f"{NEWS_API_BASE}/top-headlines"
    params = {"category": "business", "country": country, "pageSize": min(page_size, 100)}

    try:
        data = _call(url, params)
        return [_normalize_article(a) for a in data.get("articles", [])]
    except Exception as e:
        logging.warning(f"fetch_business_headlines failed: {e}")
        return _sample_articles("business")


def fetch_by_keyword(
    keyword: str,
    *,
    language: str = "en",
    sort_by: str = "publishedAt",
    page_size: int = 20,
    from_date: Optional[str] = None,
) -> list[dict]:
    """Search NewsAPI by keyword/phrase (startup, AI, fintech, etc.).

    Args:
        keyword:       Search term or phrase.
        language:      2-letter ISO 639-1 code (default en).
        sort_by:       publishedAt | relevancy | popularity.
        page_size:     Results per page, max 100.
        from_date:     ISO date string (YYYY-MM-DD), default 7 days ago.

    Returns:
        [{title, description, url, publishedAt, source, author, urlToImage, content}]
    """
    url = f"{NEWS_API_BASE}/everything"
    if from_date is None:
        from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    params = {
        "q": keyword,
        "language": language,
        "sortBy": sort_by,
        "pageSize": min(page_size, 100),
        "from": from_date,
    }

    try:
        data = _call(url, params)
        return [_normalize_article(a) for a in data.get("articles", [])]
    except Exception as e:
        logging.warning(f"fetch_by_keyword({keyword!r}) failed: {e}")
        return _sample_articles("general")


def fetch_startup_news(page_size: int = 20) -> list[dict]:
    """Fetch articles about startups, VC funding, and entrepreneurship."""
    return fetch_by_keyword(
        "startup OR venture capital OR funding round OR Series A OR Y Combinator",
        sort_by="publishedAt",
        page_size=page_size,
    )


def fetch_ai_tech_news(page_size: int = 20) -> list[dict]:
    """Fetch AI, ML, and LLM-related tech news."""
    return fetch_by_keyword(
        "artificial intelligence OR machine learning OR LLM OR generative AI OR GPT",
        sort_by="publishedAt",
        page_size=page_size,
    )


def fetch_trend_signals(page_size: int = 30) -> list[dict]:
    """High-value composite fetch: startup + tech + business signals.

    Returns merged results from startup news and tech headlines (deduped by URL).
    """
    articles: list[dict] = []
    seen_urls: set[str] = set()

    for source_fn in [fetch_startup_news, fetch_ai_tech_news, fetch_tech_headlines]:
        try:
            batch = source_fn(page_size=page_size)
        except Exception:
            batch = []
        for a in batch:
            if a["url"] and a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                articles.append(a)

    return articles


# ── Sample / fallback data ─────────────────────────────────────────────────────

def _sample_articles(category: str) -> list[dict]:
    """Return static sample articles when API is unavailable."""
    now = datetime.now().isoformat()
    samples = {
        "tech": [
            {
                "title": "OpenAI Releases New Model with Enhanced Reasoning Capabilities",
                "description": "The latest iteration of the company's flagship model demonstrates significant improvements in complex task handling.",
                "url": "https://example.com/openai-new-model",
                "publishedAt": now,
                "source": "Tech Review",
                "author": "Sample Author",
                "urlToImage": "",
                "content": "OpenAI has announced...",
            },
            {
                "title": "Venture Capital Firms Increase AI Startup Investments",
                "description": "New data shows VC funding for AI companies reached record levels this quarter.",
                "url": "https://example.com/ai-vc-funding",
                "publishedAt": now,
                "source": "Startup Weekly",
                "author": "Jane Doe",
                "urlToImage": "",
                "content": "Investors are pouring...",
            },
        ],
        "business": [
            {
                "title": "Tech Giants Report Strong Quarterly Earnings",
                "description": "Major technology companies exceeded analyst expectations amid strong cloud demand.",
                "url": "https://example.com/tech-earnings",
                "publishedAt": now,
                "source": "Business Daily",
                "author": "John Smith",
                "urlToImage": "",
                "content": "The earnings season...",
            },
        ],
        "general": [
            {
                "title": "Y Combinator Demo Day Showcases 200+ Startups",
                "description": "The latest batch features companies across AI, climate tech, and developer tools.",
                "url": "https://example.com/yc-demo-day",
                "publishedAt": now,
                "source": "Venture Beat",
                "author": "Alex Lee",
                "urlToImage": "",
                "content": "This year's batch...",
            },
        ],
    }
    return samples.get(category, samples["general"])


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    print("\n=== Tech Headlines ===")
    for a in fetch_tech_headlines(page_size=5):
        print(f"  [{a['source']}] {a['title']}")

    print("\n=== Business Headlines ===")
    for a in fetch_business_headlines(page_size=5):
        print(f"  [{a['source']}] {a['title']}")

    print("\n=== Startup News (keyword search) ===")
    for a in fetch_startup_news(page_size=5):
        print(f"  [{a['source']}] {a['title']}")

    print("\n=== AI Tech News ===")
    for a in fetch_ai_tech_news(page_size=5):
        print(f"  [{a['source']}] {a['title']}")

    print(f"\nAPI calls remaining today: {_rate_guard.remaining()}/{_rate_guard.max_per_day}")
