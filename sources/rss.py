"""RSS Newsletter Parser — aggregates trending newsletters as trend signals.

Tier 1 — Unlimited Free
Supports: RSS 2.0 and Atom 1.0 feeds.
No auth required.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from typing import Optional

import requests


# ─── RSS Source Registry ──────────────────────────────────────────────────────

NEWSLETTERS: list[dict] = [
    {
        "id": "tldr",
        "name": "TLDR",
        "description": "Daily tech newsletter digest",
        "url": "https://tldr.tech/rss",
    },
    {
        "id": "a16z",
        "name": "a16z",
        "description": "Andreessen Horowitz insights",
        "url": "https://www.a16z.news/feed/",
    },
    {
        "id": "lenny",
        "name": "Lenny's Newsletter",
        "description": "Product, growth & startup wisdom",
        "url": "https://www.lennysnewsletter.com/feed/",
    },
    {
        "id": "densediscovery",
        "name": "Dense Discovery",
        "description": "Design, productivity & technology",
        "url": "https://www.densediscovery.com/feed/",
    },
    {
        "id": "notboring",
        "name": "Not Boring",
        "description": "Business strategy & mental models",
        "url": "https://www.notboring.co/feed",
    },
    {
        "id": "stratechery",
        "name": "Stratechery",
        "description": "Tech industry analysis (free posts)",
        "url": "https://stratechery.com/feed/",
    },
    {
        "id": "generalist",
        "name": "The Generalist",
        "description": "High-signal writes on technology & business",
        "url": "https://generalist.substack.com/feed/",
    },
    {
        "id": "margins",
        "name": "Margins",
        "description": "Rereading great books, distilling insights",
        "url": "https://margins.com/feed/",
    },
]

# ─── RSS Parsing Utilities ────────────────────────────────────────────────────


def _parse_date(date_str: str) -> Optional[str]:
    """Parse various date formats and return ISO string."""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",   # RFC 822: "Mon, 01 Jan 2024 12:00:00 +0000"
        "%Y-%m-%dT%H:%M:%S%z",          # ISO 8601
        "%Y-%m-%dT%H:%M:%SZ",          # ISO 8601 UTC
        "%Y-%m-%dT%H:%M:%S.%f%z",      # ISO 8601 with microseconds
        "%Y-%m-%d",                    # Simple date
    ]
    cleaned = date_str.strip()
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).isoformat()
        except ValueError:
            continue
    return None


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _extract_thumbnail(item_root) -> Optional[str]:
    """Try to extract thumbnail/image URL from an RSS item."""
    # media:thumbnail
    for el in item_root.iter():
        if el.tag.endswith("thumbnail") or el.tag.endswith("image"):
            url = el.get("url") or (el.text or "")
            if url:
                return url.strip()
    # enclosure (image type)
    for enclosure in item_root.findall("enclosure"):
        mime = enclosure.get("type", "")
        if "image" in mime:
            return enclosure.get("url")
    # linked image in description
    desc_el = item_root.find("description") if item_root.find("description") is not None else item_root.find("content:encoded")
    if desc_el is not None and desc_el.text:
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc_el.text)
        if img_match:
            return img_match.group(1)
    return None


def _parse_rss_item(item_el) -> Optional[dict]:
    """Parse a single <item> from an RSS 2.0 feed."""
    title = _strip_html(
        (item_el.find("title").text or "") if item_el.find("title") is not None else ""
    )

    # Link: <link>text</link> or <link href="..."> (Atom compat)
    link_el = item_el.find("link")
    if link_el is not None:
        link = link_el.get("href") or (link_el.text or "").strip()
    else:
        link = ""

    # Description / summary
    desc_el = item_el.find("description") if item_el.find("description") is not None else item_el.find("content:encoded")
    description = _strip_html(desc_el.text) if desc_el is not None and desc_el.text else ""

    # Author / creator
    author_el = item_el.find("author") or item_el.find("dc:creator")
    author = author_el.text.strip() if author_el is not None and author_el.text else ""

    # Publication date
    date_el = item_el.find("pubDate") if item_el.find("pubDate") is not None else item_el.find("dc:date")
    pub_date = _parse_date(date_el.text) if date_el is not None and date_el.text else None

    # GUID / ID
    guid_el = item_el.find("guid")
    guid = guid_el.text.strip() if guid_el is not None and guid_el.text else link

    # Categories
    cats = []
    for cat in item_el.findall("category"):
        if cat.text:
            cats.append(cat.text.strip())
    for cat in item_el.findall("category[@domain]"):
        if cat.text:
            cats.append(cat.text.strip())

    # Thumbnail
    thumbnail = _extract_thumbnail(item_el)

    if not title:
        return None

    return {
        "title": title,
        "url": link,
        "description": description[:300] if description else "",
        "author": author,
        "published": pub_date,
        "guid": guid,
        "categories": cats,
        "thumbnail": thumbnail,
    }


def _parse_atom_entry(entry_el) -> Optional[dict]:
    """Parse a single <entry> from an Atom 1.0 feed."""
    # Title
    title_el = entry_el.find("title")
    title = _strip_html(title_el.text) if title_el is not None and title_el.text else ""

    # Link — prefer alternate rel
    link = ""
    for link_el in entry_el.findall("link"):
        rel = link_el.get("rel", "alternate")
        href = link_el.get("href", "")
        if rel == "alternate" and href:
            link = href
            break
        elif not link and href:
            link = href

    # Summary / content
    summary_el = entry_el.find("summary") if entry_el.find("summary") is not None else entry_el.find("content")
    description = _strip_html(summary_el.text) if summary_el is not None and summary_el.text else ""

    # Author name
    author_el = entry_el.find("author")
    author = ""
    if author_el is not None:
        name_el = author_el.find("name")
        author = name_el.text.strip() if name_el is not None and name_el.text else ""

    # Published / updated
    date_el = entry_el.find("published") if entry_el.find("published") is not None else entry_el.find("updated")
    pub_date = _parse_date(date_el.text) if date_el is not None and date_el.text else None

    # ID
    id_el = entry_el.find("id")
    guid = id_el.text.strip() if id_el is not None and id_el.text else link

    # Categories
    cats = [el.get("term", "") for el in entry_el.findall("category") if el.get("term")]

    # Thumbnail
    thumbnail = _extract_thumbnail(entry_el)

    if not title:
        return None

    return {
        "title": title,
        "url": link,
        "description": description[:300] if description else "",
        "author": author,
        "published": pub_date,
        "guid": guid,
        "categories": cats,
        "thumbnail": thumbnail,
    }


def _detect_and_parse(xml_text: str) -> list[dict]:
    """Auto-detect RSS 2.0 vs Atom 1.0 and parse accordingly."""
    root = ET.fromstring(xml_text)

    # Atom: <feed><entry>...</entry></feed>
    if root.tag.endswith("feed"):
        return [
            item for item in (_parse_atom_entry(e) for e in root.findall("entry"))
            if item is not None
        ]

    # RSS 2.0: <rss><channel><item>...</item></channel></rss>
    # or <rdf:RDF><channel><item>...</item></channel></rdf:RDF>
    channel = root.find("channel")
    if channel is None:
        # Try finding items at root level
        items = [
            _parse_rss_item(i) for i in root.findall("item")
        ]
    else:
        items = [
            _parse_rss_item(i) for i in channel.findall("item")
        ]

    return [item for item in items if item is not None]


# ─── Public API ───────────────────────────────────────────────────────────────


def fetch_newsletter(feed_id: str, limit: int = 10) -> list[dict]:
    """Fetch items from a single newsletter RSS feed.

    Args:
        feed_id: Newsletter ID from NEWSLETTERS registry (e.g. "tldr", "a16z")
        limit: Maximum number of items to return

    Returns:
        [{title, url, description, author, published, guid, categories, thumbnail, source}]
    """
    feed = next((f for f in NEWSLETTERS if f["id"] == feed_id), None)
    if not feed:
        return []

    try:
        resp = requests.get(
            feed["url"],
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TrendRadar/1.0; +https://trendradar)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        return []

    try:
        items = _detect_and_parse(resp.text)
    except Exception:
        return []

    for item in items[:limit]:
        item["source"] = feed["name"]
        item["source_id"] = feed_id

    return items[:limit]


def fetch_all_newsletters(limit_per_feed: int = 10) -> list[dict]:
    """Fetch latest items from all registered newsletters.

    Returns:
        Flat list of items from all feeds, sorted newest-first.
        Each item includes: title, url, description, author, published, guid,
        categories, thumbnail, source, source_id
    """
    all_items = []

    for feed in NEWSLETTERS:
        items = fetch_newsletter(feed["id"], limit=limit_per_feed)
        all_items.extend(items)

    # Sort by publish date (newest first)
    all_items.sort(
        key=lambda x: x.get("published") or "",
        reverse=True,
    )

    return all_items


def get_trending_topics(newsletters: list[dict], top_n: int = 10) -> list[tuple]:
    """Extract trending topics from newsletter items.

    Returns:
        [(keyword, score), ...] sorted by frequency
    """
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "may", "might",
        "can", "with", "this", "that", "these", "those", "i", "you", "he", "she",
        "it", "we", "they", "what", "which", "who", "when", "where", "how", "why",
        "not", "no", "yes", "all", "each", "every", "both", "few", "more", "most",
        "other", "some", "such", "only", "own", "same", "so", "than", "too", "very",
        "just", "about", "from", "into", "through", "during", "before", "after",
        "above", "below", "between", "under", "again", "further", "then", "once",
        "here", "there", "your", "our", "their", "its", "new", "use", "using",
        "used", "open", "source", "one", "two", "get", "got", "make", "made",
        "read", "see", "want", "know", "think", "also", "back", "first", "last",
        "long", "great", "little", "way", "well", "still", "even", "right",
        "take", "come", "many", "now", "like", "over", "out",
    }

    counter: dict = {}

    for item in newsletters:
        text = f"{item.get('title', '')} {item.get('description', '')}".lower()
        words = re.findall(r"\b[a-z][a-z0-9]{2,}\b", text)
        for w in words:
            if w not in stop_words:
                counter[w] = counter.get(w, 0) + 1

    # Return top N by frequency
    sorted_words = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    return sorted_words[:top_n]


# ─── CLI / Test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Fetching all newsletters...")
    items = fetch_all_newsletters(limit_per_feed=5)
    print(f"\nTotal items fetched: {len(items)}\n")

    for item in items[:10]:
        print(f"[{item['source']}] {item['title']}")
        print(f"  → {item['url']}")
        if item.get("description"):
            print(f"  {item['description'][:120]}...")
        print()

    print("\n--- Trending Keywords ---")
    topics = get_trending_topics(items)
    for kw, score in topics:
        print(f"  {kw}: {score}")
