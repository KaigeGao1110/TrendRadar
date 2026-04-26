"""HackerNews Comments Fetcher — fetches top comments from HN stories.

Extends the basic hackernews.py with comment depth.
Provides pain_density and tech_feasibility dimensions — user feedback and technical discussions.
"""

import requests
from datetime import datetime

HN_API = "https://hacker-news.firebaseio.com/v0"

HEADERS = {
    "User-Agent": "TrendRadar/2.0 (HN research bot)",
}

REQUEST_TIMEOUT = 30


def _fetch_item(item_id: int) -> dict | None:
    """Fetch a single HN item (story or comment) by ID."""
    try:
        url = f"{HN_API}/item/{item_id}.json"
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️ HN item {item_id} fetch failed: {e}")
        return None


def _fetch_top_stories(limit: int = 30) -> list[int]:
    """Fetch top story IDs from HN."""
    try:
        url = f"{HN_API}/topstories.json"
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()[:limit]
    except Exception as e:
        print(f"⚠️ HN topstories fetch failed: {e}")
        return []


def fetch_latest(story_limit: int = 20, comments_per_story: int = 5) -> list[dict]:
    """Fetch top comments from HN top stories.

    Args:
        story_limit: Number of top stories to fetch comments for.
        comments_per_story: Max comments per story.

    Returns:
        List of dicts with title, url, source, description, industry,
        published_at, metadata.
    """
    story_ids = _fetch_top_stories(limit=story_limit)
    results = []

    for sid in story_ids:
        story = _fetch_item(sid)
        if not story or story.get("type") != "story":
            continue

        story_title = story.get("title", "")
        story_url = story.get("url", f"https://news.ycombinator.com/item?id={sid}")
        story_score = story.get("score", 0)
        story_by = story.get("by", "unknown")
        story_time = story.get("time", 0)

        published_at = (
            datetime.utcfromtimestamp(story_time).isoformat() + "Z"
            if story_time
            else None
        )

        # Get comment IDs (kids)
        kid_ids = story.get("kids", [])[:comments_per_story]
        if not kid_ids:
            # No comments on this story, still include the story itself
            results.append({
                "title": story_title,
                "url": story_url,
                "source": "hackernews_comments",
                "description": f"HN story with {story_score} points, no top comments yet.",
                "industry": ["tech"],
                "published_at": published_at,
                "metadata": {
                    "story_id": sid,
                    "story_title": story_title,
                    "story_url": story_url,
                    "story_score": story_score,
                    "story_by": story_by,
                    "comment_text": None,
                    "comment_by": None,
                    "comment_score": None,
                    "is_story_only": True,
                },
            })
            continue

        for kid_id in kid_ids:
            comment = _fetch_item(kid_id)
            if not comment or comment.get("type") != "comment":
                continue

            comment_text = comment.get("text", "")
            # Strip HTML from comment text
            import re
            comment_text = re.sub(r"<[^>]+>", "", comment_text)
            comment_text = comment_text.strip()[:500]

            comment_by = comment.get("by", "unknown")
            comment_score = comment.get("score", 0) or 0
            comment_time = comment.get("time", 0)

            comment_published = (
                datetime.utcfromtimestamp(comment_time).isoformat() + "Z"
                if comment_time
                else published_at
            )

            results.append({
                "title": f'Comment on "{story_title[:50]}..."',
                "url": f"https://news.ycombinator.com/item?id={kid_id}",
                "source": "hackernews_comments",
                "description": comment_text,
                "industry": ["tech"],
                "published_at": comment_published,
                "metadata": {
                    "story_id": sid,
                    "story_title": story_title,
                    "story_url": story_url,
                    "story_score": story_score,
                    "story_by": story_by,
                    "comment_text": comment_text,
                    "comment_by": comment_by,
                    "comment_score": comment_score,
                    "is_story_only": False,
                },
            })

    # Sort by story score descending
    results.sort(
        key=lambda x: x.get("metadata", {}).get("story_score", 0),
        reverse=True,
    )

    return results[:50]


if __name__ == "__main__":
    items = fetch_latest(story_limit=10, comments_per_story=3)
    print(f"Fetched {len(items)} HN stories/comments\n")
    for item in items[:5]:
        meta = item.get("metadata", {})
        if meta.get("is_story_only"):
            print(f"📖 [{meta['story_score']} pts] {meta['story_title']}")
        else:
            print(f"💬 [{meta['story_score']} pts] {meta['story_title'][:40]}...")
            print(f"   by {meta['comment_by']}: {item['description'][:80]}...")
        print()
