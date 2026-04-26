"""Reddit Posts Fetcher — fetches trending posts from startup/tech subreddits.

Uses Reddit's public JSON endpoints (no API key required).
Provides pain_density dimension — real user problems and complaints.
"""

import requests
from datetime import datetime

HEADERS = {
    "User-Agent": "TrendRadar/2.0 (research bot)",
    "Accept": "application/json",
}

SUBREDDITS = [
    "startups",
    "SaaS",
    "Entrepreneur",
    "smallbusiness",
    "SideProject",
]

REQUEST_TIMEOUT = 30


def _fetch_subreddit(subreddit: str, limit: int = 25) -> list[dict]:
    """Fetch new posts from a single subreddit via JSON endpoint."""
    url = f"https://www.reddit.com/r/{subreddit}/new/.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"⚠️ Reddit r/{subreddit} fetch failed: {e}")
        return []

    posts = []
    children = data.get("data", {}).get("children", [])
    for child in children[:limit]:
        d = child.get("data", {})
        if not d:
            continue

        created_utc = d.get("created_utc", 0)
        published_at = (
            datetime.utcfromtimestamp(created_utc).isoformat() + "Z"
            if created_utc
            else None
        )

        posts.append({
            "title": d.get("title", ""),
            "url": d.get("url", f"https://www.reddit.com/r/{subreddit}/comments/{d.get('id', '')}"),
            "source": "reddit",
            "description": (d.get("selftext", "") or "")[:500],
            "industry": [subreddit],
            "published_at": published_at,
            "metadata": {
                "subreddit": subreddit,
                "score": d.get("score", 0),
                "num_comments": d.get("num_comments", 0),
                "author": d.get("author", "[deleted]"),
                "upvote_ratio": d.get("upvote_ratio", 0),
                "link_flair_text": d.get("link_flair_text", ""),
                "is_self": d.get("is_self", False),
                "over_18": d.get("over_18", False),
            },
        })

    return posts


def fetch_latest(limit_per_sub: int = 10) -> list[dict]:
    """Fetch latest posts from all configured subreddits.

    Args:
        limit_per_sub: Max posts per subreddit.

    Returns:
        List of dicts with title, url, source, description, industry,
        published_at, metadata.
    """
    all_posts = []
    for sub in SUBREDDITS:
        posts = _fetch_subreddit(sub, limit=limit_per_sub)
        all_posts.extend(posts)

    # Sort by published_at descending
    all_posts.sort(key=lambda x: x.get("published_at") or "", reverse=True)

    return all_posts[:50]


if __name__ == "__main__":
    items = fetch_latest(limit_per_sub=5)
    print(f"Fetched {len(items)} Reddit posts\n")
    for item in items[:5]:
        meta = item.get("metadata", {})
        print(f"[r/{meta['subreddit']}] {item['title']}")
        print(f"  ↑ {meta['score']}  💬 {meta['num_comments']}  {item['url']}")
        print()
