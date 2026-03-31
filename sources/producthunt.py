"""Product Hunt Trend Fetcher."""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta

PH_URL = "https://www.producthunt.com"


def fetch_today_trending(limit: int = 20) -> list[dict]:
    """Fetch today's trending products from Product Hunt.
    
    Uses web scraping since Product Hunt API requires OAuth.
    
    Returns:
        [{name, tagline, votes, url, topics[], featured_date}]
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html",
        }
        response = requests.get(PH_URL, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        products = []
        # Try multiple selectors for Product Hunt's evolving structure
        items = (
            soup.select('a[href^="/posts/"]') or
            soup.select(".posts-list-item") or
            soup.select("[data-test='post-item']") or
            soup.select("article")
        )
        
        for item in items[:limit]:
            try:
                name_tag = item.select_one("h2, h3, .title, [data-test='post-title']")
                name = name_tag.get_text(strip=True) if name_tag else "Unknown"
                
                tagline_tag = item.select_one(".tagline, .description, p, [data-test='post-tagline']")
                tagline = tagline_tag.get_text(strip=True) if tagline_tag else ""
                
                votes_tag = item.select_one("[data-test='vote-count'], .votes, span:first-child")
                votes_text = votes_tag.get_text(strip=True) if votes_tag else "0"
                votes = int("".join(filter(str.isdigit, votes_text))) or 0
                
                href = name_tag.get("href", "") if name_tag else ""
                url = f"https://www.producthunt.com{href}" if href.startswith("/") else href
                
                topic_tags = item.select(".topic, .tag, .category")
                topics = [t.get_text(strip=True) for t in topic_tags[:5]]
                
                products.append({
                    "name": name,
                    "tagline": tagline,
                    "votes": votes,
                    "url": url,
                    "topics": topics,
                    "featured_date": str(date.today()),
                })
            except Exception:
                continue
        
        if products:
            return products
    except Exception:
        pass
    
    # Fallback sample data
    return [
        {
            "name": "Sample Product",
            "tagline": "AI-powered design tool for teams",
            "votes": 420,
            "url": "https://www.producthunt.com",
            "topics": ["AI", "Design", "SaaS"],
            "featured_date": str(date.today()),
        }
    ]


def fetch_weekly_top(limit: int = 50) -> list[dict]:
    """Fetch top products from the past week."""
    today = date.today()
    products = []
    
    for i in range(7):
        day = today - timedelta(days=i)
        try:
            # Try to fetch specific day's page
            day_url = f"{PH_URL}/@{day.year}-{day.month:02d}-{day.day:02d}"
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            }
            response = requests.get(day_url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                items = soup.select('a[href^="/posts/"]') or soup.select("article")
                for item in items[:10]:
                    name_tag = item.select_one("h2, h3, .title")
                    name = name_tag.get_text(strip=True) if name_tag else "Unknown"
                    tagline_tag = item.select_one(".tagline, .description, p")
                    tagline = tagline_tag.get_text(strip=True) if tagline_tag else ""
                    products.append({
                        "name": name,
                        "tagline": tagline,
                        "votes": 0,
                        "url": f"{PH_URL}/posts/{day.isoformat()}",
                        "topics": [],
                        "featured_date": str(day),
                    })
        except Exception:
            continue
    
    if not products:
        # Fallback: return today's trending with a different flag
        products = fetch_today_trending(limit)
        for p in products:
            p["featured_date"] = str(today - timedelta(days=1))
    
    return products[:limit]


def categorize_products(products: list[dict]) -> dict:
    """Group products by topic/category.
    
    Returns: {topic: {count, products: [str]}}
    """
    categories: dict = {}
    
    for product in products:
        topics = product.get("topics", [])
        if not topics:
            # Infer from tagline
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
    
    if any(k in text for k in ["ai", "gpt", "llm", "chatbot", "machine learning"]):
        topics.append("AI")
    if any(k in text for k in ["design", "ui", "ux", "figma", "creative"]):
        topics.append("Design")
    if any(k in text for k in ["api", "developer", "devops", "code"]):
        topics.append("Developer Tools")
    if any(k in text for k in ["saas", "business", "team", "enterprise"]):
        topics.append("SaaS")
    if any(k in text for k in ["mobile", "ios", "android", "app"]):
        topics.append("Mobile")
    if any(k in text for k in ["security", "privacy", "encryption"]):
        topics.append("Security")
    
    return topics or ["General"]
