"""ProductHunt Deep Fetcher — scrapes detailed product information.

Extends the basic producthunt.py with more detailed data.
Provides pain_density and tech_feasibility dimensions.
Uses web scraping since API requires token.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

PRODUCTHUNT_BASE = "https://www.producthunt.com"
PRODUCTHUNT_RSS = "https://www.producthunt.com/feed"

REQUEST_TIMEOUT = 30


def _fetch_via_rss(limit: int = 30) -> list[dict]:
    """Fetch products via ProductHunt RSS feed (fallback when HTML is blocked)."""
    import xml.etree.ElementTree as ET
    from html import unescape
    
    try:
        resp = requests.get(
            PRODUCTHUNT_RSS,
            headers={"User-Agent": "Mozilla/5.0 Chrome/120"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ ProductHunt RSS fetch failed: {e}")
        return []
    
    root = ET.fromstring(resp.text)
    products = []
    
    # Handle both Atom and RSS formats
    ATOM = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(f"{ATOM}entry") or root.findall(".//item")
    
    for entry in entries[:limit]:
        # Name
        name_el = entry.find(f"{ATOM}title")
        if name_el is None:
            name_el = entry.find("title")
        name = (name_el.text or "").strip() if name_el is not None else ""
        
        # URL
        link_el = entry.find(f"{ATOM}link")
        if link_el is not None:
            product_url = link_el.get("href", "")
        else:
            link_el = entry.find("link")
            product_url = (link_el.text or "").strip() if link_el is not None else ""
        
        # Content/description
        content_el = entry.find(f"{ATOM}content")
        if content_el is None:
            content_el = entry.find("content")
        if content_el is None:
            content_el = entry.find("description")
        content = (content_el.text or "") if content_el is not None else ""
        
        # Extract tagline from first <p>
        tagline = ""
        if content:
            content_decoded = unescape(content)
            p_match = re.search(r"<p[^>]*>(.*?)</p>", content_decoded, re.DOTALL)
            if p_match:
                tagline = re.sub(r"<[^>]+>", "", p_match.group(1)).strip()
        
        # Published date
        pub_el = entry.find(f"{ATOM}published")
        if pub_el is None:
            pub_el = entry.find(f"{ATOM}updated")
        if pub_el is None:
            pub_el = entry.find("pubDate")
        pub_date = (pub_el.text or "") if pub_el is not None else ""
        featured_date = pub_date[:10] if pub_date else datetime.utcnow().strftime("%Y-%m-%d")
        
        # Infer topics
        topics = _infer_topics(tagline)
        
        if name:
            products.append({
                "title": name,
                "url": product_url,
                "source": "producthunt_deep",
                "description": tagline[:500] if tagline else "",
                "industry": topics,
                "published_at": featured_date,
                "metadata": {
                    "name": name,
                    "tagline": tagline,
                    "topics": topics,
                    "votes_count": 0,  # RSS doesn't include votes
                    "comments_count": 0,
                },
            })
    
    return products


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


def _parse_producthunt_page(url: str) -> list[dict]:
    """Parse Product Hunt trending page for product cards."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ ProductHunt page fetch failed ({url}): {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    products = []

    # Product Hunt uses <div data-test="post-item"> for each product
    # Also try [data-test="item"] or .post-item
    items = soup.select('[data-test="post-item"]') or soup.select('[data-test="item"]') or soup.select(".post-item")

    for item in items[:30]:
        # Name and URL
        name_el = item.select_one('[data-test="post-name"]') or item.select_one("h3")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)

        link_el = name_el.find_parent("a") or item.select_one("a")
        if link_el:
            path = link_el.get("href", "")
            product_url = f"{PRODUCTHUNT_BASE}{path}" if path.startswith("/") else path
        else:
            product_url = PRODUCTHUNT_BASE

        # Tagline
        tagline_el = item.select_one('[data-test="post-tagline"]') or item.select_one("p")
        tagline = tagline_el.get_text(strip=True) if tagline_el else ""

        # Description (often in data attributes or hidden divs)
        description = tagline  # Initial fallback

        # Topics/categories
        topics = []
        topic_els = item.select('[data-test="post-topic"]') or item.select(".topic")
        for t in topic_els:
            topic = t.get_text(strip=True)
            if topic:
                topics.append(topic)

        # Votes count
        votes = 0
        vote_el = item.select_one('[data-test="vote-count"]') or item.select_one(".vote-count")
        if vote_el:
            vote_text = vote_el.get_text(strip=True).replace(",", "")
            try:
                votes = int(vote_text)
            except ValueError:
                # Try extracting number from text like "123 upvotes"
                match = re.search(r"(\d+)", vote_text)
                if match:
                    votes = int(match.group(1))

        # Comments count
        comments = 0
        comment_el = item.select_one('[data-test="post-comment-count"]') or item.select_one(".comment-count")
        if comment_el:
            comment_text = comment_el.get_text(strip=True)
            match = re.search(r"(\d+)", comment_text)
            if match:
                comments = int(match.group(1))

        # Featured date (if available)
        featured_date = datetime.utcnow().isoformat() + "Z"
        time_el = item.select_one("time")
        if time_el:
            dt = time_el.get("datetime") or time_el.get("title")
            if dt:
                featured_date = dt

        products.append({
            "title": name,
            "url": product_url,
            "source": "producthunt_deep",
            "description": description[:500] if description else tagline[:500],
            "industry": topics[:3] if topics else ["tech"],
            "published_at": featured_date,
            "metadata": {
                "name": name,
                "tagline": tagline,
                "topics": topics,
                "votes_count": votes,
                "comments_count": comments,
            },
        })

    return products


def _fetch_product_detail(product_url: str) -> dict:
    """Fetch additional details from a product's detail page."""
    try:
        resp = requests.get(product_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    detail = {}

    # Full description
    desc_el = soup.select_one('[data-test="post-description"]') or soup.select_one(".post-description")
    if desc_el:
        detail["full_description"] = desc_el.get_text(strip=True)[:1000]

    # Makers
    makers = []
    maker_els = soup.select('[data-test="maker"]') or soup.select(".maker-name")
    for m in maker_els[:5]:
        maker_name = m.get_text(strip=True)
        if maker_name:
            makers.append(maker_name)
    if makers:
        detail["makers"] = makers

    # Additional topics
    additional_topics = []
    topic_els = soup.select('[data-test="topic"]') or soup.select(".topic-tag")
    for t in topic_els:
        topic = t.get_text(strip=True)
        if topic and topic not in additional_topics:
            additional_topics.append(topic)
    if additional_topics:
        detail["additional_topics"] = additional_topics

    return detail


def fetch_latest(deep_fetch: bool = False, max_detail_products: int = 10) -> list[dict]:
    """Fetch trending products from Product Hunt via RSS feed.

    HTML scraping is not used because PH returns 403 for automated requests.
    RSS feed is the reliable, no-auth-needed source.

    Args:
        deep_fetch: If True, fetch detail pages for top products (slower).
        max_detail_products: Max products to deep fetch if deep_fetch=True.

    Returns:
        List of dicts with title, url, source, description, industry,
        published_at, metadata.
    """
    all_products = _fetch_via_rss(limit=50)

    # Sort by votes (RSS doesn't include votes, but keep for consistency)
    all_products.sort(
        key=lambda x: x.get("metadata", {}).get("votes_count", 0),
        reverse=True,
    )

    # Optionally deep fetch for top products
    if deep_fetch:
        for i, p in enumerate(all_products[:max_detail_products]):
            detail = _fetch_product_detail(p["url"])
            if detail:
                p["metadata"]["deep"] = detail
                if "full_description" in detail:
                    p["description"] = detail["full_description"][:500]

    return all_products[:50]


if __name__ == "__main__":
    items = fetch_latest(deep_fetch=False)
    print(f"Fetched {len(items)} ProductHunt products\n")
    for item in items[:10]:
        meta = item.get("metadata", {})
        votes = meta.get("votes_count", 0)
        comments = meta.get("comments_count", 0)
        topics = ", ".join(meta.get("topics", [])[:3])
        print(f"🚀 [{votes}↑ {comments}💬] {item['title']}")
        print(f"   {meta.get('tagline', '')[:80]}")
        if topics:
            print(f"   Topics: {topics}")
        print()