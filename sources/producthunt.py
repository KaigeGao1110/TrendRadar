"""Product Hunt Trend Fetcher — uses PH RSS feed (no auth needed)."""

import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html import unescape

import requests


PH_RSS_URL = "https://www.producthunt.com/feed"

# Atom/RSS namespace map
PH_NS = {}


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

        root = ET.fromstring(response.text)
        products = []
        today = str(date.today())

        # Handle both Atom (default) and RSS formats
        entries = root.findall(".//entry") or root.findall(".//item")

        for entry in entries[:limit]:
            name_el = entry.find("title")
            name = name_el.text.strip() if name_el is not None and name_el.text else ""

            content_el = entry.find("content")
            content = content_el.text if content_el is not None and content_el.text else ""

            # Extract URL from link tag (handles href attribute)
            url = ""
            link_el = entry.find("link")
            if link_el is not None:
                url = link_el.get("href") or ""
            else:
                # Fallback: search for link with producthunt.com/products
                for link in entry.findall("link"):
                    href = link.get("href", "")
                    if "producthunt.com/products" in href:
                        url = href
                        break

            # Decode HTML entities and extract first <p> as tagline
            tagline = ""
            if content:
                content_decoded = unescape(content)
                p_match = re.search(r"<p[^>]*>(.*?)</p>", content_decoded, re.DOTALL)
                if p_match:
                    tagline = re.sub(r"<[^>]+>", "", p_match.group(1)).strip()

            # Extract publish date
            pub_el = entry.find("published") or entry.find("pubDate") or entry.find("dc:date")
            pub_date = pub_el.text if pub_el is not None and pub_el.text else ""
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

        return products

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
