"""Product Hunt Trend Fetcher — uses PH RSS feed (no auth needed)."""

import re
import requests
from datetime import datetime, date, timedelta
from html import unescape


PH_RSS_URL = "https://www.producthunt.com/feed"


def fetch_today_trending(limit: int = 20) -> list[dict]:
    """Fetch today's trending products from Product Hunt RSS feed.

    Returns:
        [{name, tagline, votes, url, topics[], featured_date}]
    """
    try:
        response = requests.get(
            PH_RSS_URL,
            headers={"User-Agent": "Mozilla/5.0 Chrome/120"},
            timeout=15,
        )
        response.raise_for_status()

        products = []
        today = str(date.today())

        # Parse Atom XML manually (no lxml dependency needed)
        entries = response.text.split("<entry>")[1:]  # skip feed header

        for entry in entries[:limit]:
            name = _extract_tag(entry, "title")
            content = _extract_tag(entry, "content")

            # Extract URL from link tag
            url_match = re.search(r'href="(https://www\.producthunt\.com/products/[^"]+)"', entry)
            url = url_match.group(1) if url_match else ""

            # Extract tagline from content (first <p> tag)
            tagline = ""
            if content:
                # Decode HTML entities first
                content_decoded = unescape(content)
                tagline_match = re.search(r'<p>\s*(.*?)\s*</p>', content_decoded, re.DOTALL)
                if tagline_match:
                    tagline = re.sub(r'<[^>]+>', '', tagline_match.group(1)).strip()

            # Extract publish date
            pub_date = _extract_tag(entry, "published")
            featured = pub_date[:10] if pub_date else today

            if name:
                products.append({
                    "name": name,
                    "tagline": tagline,
                    "votes": 0,  # RSS doesn't include votes
                    "url": url,
                    "topics": _infer_topics(tagline),
                    "featured_date": featured,
                })

        return products[:limit]

    except Exception as e:
        print(f"PH fetch error: {e}")
        return []


def fetch_weekly_top(limit: int = 50) -> list[dict]:
    """Fetch top products from the past week via RSS."""
    all_products = fetch_today_trending(50)

    # Filter to last 7 days
    today = date.today()
    week_ago = today - timedelta(days=7)

    weekly = [
        p for p in all_products
        if p.get("featured_date", "") >= str(week_ago)
    ]

    return weekly[:limit]


def _extract_tag(xml: str, tag: str) -> str:
    """Extract text content from an XML tag."""
    match = re.search(rf'<{tag}[^>]*>(.*?)</{tag}>', xml, re.DOTALL)
    return match.group(1).strip() if match else ""


def categorize_products(products: list[dict]) -> dict:
    """Group products by topic/category."""
    categories: dict = {}

    for product in products:
        topics = product.get("topics", [])
        if not topics:
            topics = _infer_topics(product.get("tagline", ""))

        for topic in topics:
            if topic not in categories:
                categories[topic] = {"count": 0, "products": []}
            categories[topic]["count"] += 1
            categories[topic]["products"].append(product["name"])

    return categories


def _infer_topics(tagline: str) -> list[str]:
    """Infer topics from tagline text."""
    text = tagline.lower()
    topics = []

    topic_keywords = {
        "AI": ["ai", "gpt", "llm", "chatbot", "machine learning", "neural", "agent"],
        "Design": ["design", "ui", "ux", "figma", "creative", "prototype"],
        "Developer Tools": ["api", "developer", "devops", "code", "sdk", "cli", "terminal", "debug"],
        "SaaS": ["saas", "business", "team", "enterprise", "b2b"],
        "Mobile": ["mobile", "ios", "android", "app", "mac", "iphone"],
        "Security": ["security", "privacy", "encryption", "auth"],
        "Productivity": ["productivity", "task", "workflow", "automation", "schedule", "monitor"],
        "Marketing": ["marketing", "seo", "analytics", "growth"],
        "Finance": ["finance", "payment", "billing", "invoice"],
        "Health": ["health", "wellness", "fitness", "medical"],
    }

    for topic, keywords in topic_keywords.items():
        if any(k in text for k in keywords):
            topics.append(topic)

    return topics or ["General"]
