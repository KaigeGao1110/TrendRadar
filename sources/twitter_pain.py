"""Twitter Pain Signal Fetcher — mines pain-point tweets via RapidAPI.

Uses twitter-api45 endpoint to search for tweets expressing unmet needs,
product complaints, and tool-seeking behavior.
Provides high-signal pain_density dimension for trend scoring.
"""

import re
import time
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

API_URL = "https://twitter-api45.p.rapidapi.com/search.php"
API_HOST = "twitter-api45.p.rapidapi.com"
API_KEY = "59351167bemsh69cb04174744b16p1959cdjsn9e952846fbf3"

REQUEST_TIMEOUT = 30

PAIN_QUERIES = [
    '"I hate that"',                  # 明确不满
    '"I can\'t believe there\'s no"', # 强烈 frustration
    '"still paying for"',             # 付费但不满意
    '"waste hours on"',               # 时间浪费
    '"tried everything"',             # 已在找方案
    '"anyone know a better"',         # 现有方案不够
    '"cancelled my"',                 # 流失信号
    '"migrating away from"',          # 在换工具
    '"worst experience with"',        # 强烈负面
    '"desperately need"',             # 急迫需求
    '"looking for alternative to"',   # 找替代品
    '"so frustrated with"',           # frustration (保留原有的1个有效query)
]

# NSFW / spam filter keywords
NSFW_PATTERNS = re.compile(
    r"\b(porn|nsfw|nude|xxx|onlyfans|escort|hookup|casino|crypto giveaway|free money|click here|subscribe)\b",
    re.IGNORECASE,
)

HEADERS = {
    "x-rapidapi-host": API_HOST,
    "x-rapidapi-key": API_KEY,
}


def _fetch_query(query: str, count: int = 5) -> list[dict]:
    """Fetch tweets for a single search query."""
    params = {
        "query": query,
        "count": count,
    }
    try:
        resp = requests.get(
            API_URL,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as e:
        logger.warning("Twitter API HTTP error for '%s': %s", query, e)
        return []
    except requests.exceptions.RequestException as e:
        logger.warning("Twitter API request failed for '%s': %s", query, e)
        return []
    except (ValueError, KeyError) as e:
        logger.warning("Twitter API parse error for '%s': %s", query, e)
        return []

    timeline = data.get("timeline", [])
    if not timeline:
        return []

    tweets = []
    for entry in timeline:
        if not isinstance(entry, dict):
            continue

        tweet_id = entry.get("tweet_id") or entry.get("id") or entry.get("rest_id")
        text = entry.get("text", "")
        screen_name = entry.get("screen_name", "")
        created_at = entry.get("created_at", "")
        lang = entry.get("lang", "en")
        favorites = entry.get("favorites", 0)
        retweets = entry.get("retweets", 0)
        views = entry.get("views", 0)
        replies = entry.get("replies", 0)
        user_info = entry.get("user_info", {})
        followers = user_info.get("followers_count", 0)

        if not tweet_id or not text:
            continue

        # Only keep English
        if lang != "en":
            continue

        # Filter low-follower noise
        if followers < 10:
            continue

        # Filter NSFW / spam
        if NSFW_PATTERNS.search(text):
            continue

        # Parse date
        published_at = None
        if created_at:
            for fmt in (
                "%a %b %d %H:%M:%S %z %Y",   # "Mon Jan 01 12:00:00 +0000 2024"
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    published_at = datetime.strptime(created_at, fmt).isoformat()
                    break
                except (ValueError, TypeError):
                    continue

        # Handle views being string or int
        try:
            views = int(views)
        except (ValueError, TypeError):
            views = 0

        url = f"https://x.com/{screen_name}/status/{tweet_id}"

        tweets.append({
            "title": text,
            "url": url,
            "source": "twitter_pain",
            "description": text,
            "published_at": published_at,
            "metadata": {
                "favorites": favorites,
                "retweets": retweets,
                "views": views,
                "replies": replies,
                "screen_name": screen_name,
                "followers_count": followers,
                "search_query": query,
            },
        })

    return tweets


def fetch_latest(count_per_query: int = 5) -> list[dict]:
    """Fetch pain signal tweets from Twitter.

    Args:
        count_per_query: Max tweets per search query (default 5).

    Returns:
        List of deduplicated tweet dicts sorted by favorites descending.
    """
    seen_ids: set[str] = set()
    all_tweets: list[dict] = []

    for query in PAIN_QUERIES:
        tweets = _fetch_query(query, count=count_per_query)

        for t in tweets:
            # Deduplicate by tweet URL (handles multi-query overlap)
            if t["url"] in seen_ids:
                continue
            seen_ids.add(t["url"])
            all_tweets.append(t)

        # Polite delay between queries
        time.sleep(1)

    # Sort by engagement (favorites) descending
    all_tweets.sort(
        key=lambda x: x.get("metadata", {}).get("favorites", 0),
        reverse=True,
    )

    return all_tweets


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    items = fetch_latest()
    print(f"Fetched {len(items)} pain-signal tweets\n")
    for item in items[:10]:
        meta = item.get("metadata", {})
        print(f"  [{meta.get('favorites', 0)} likes] {item['title'][:80]}")
        print(f"    → {item['url']}")
        print(f"    query: {meta.get('search_query', '')}")
        print()
