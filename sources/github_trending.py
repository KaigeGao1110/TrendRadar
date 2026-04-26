"""GitHub Trending Fetcher — scrapes trending repositories from GitHub.

Provides tech_feasibility dimension — what technologies are gaining traction.
Uses requests + BeautifulSoup (no API key required).
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrendRadar/2.0; +https://github.com)",
    "Accept": "text/html,application/xhtml+xml",
}

TRENDING_URLS = [
    "https://github.com/trending?since=daily",
    "https://github.com/trending/python?since=daily",
    "https://github.com/trending/typescript?since=daily",
]

REQUEST_TIMEOUT = 30


def _parse_trending_page(url: str) -> list[dict]:
    """Parse a single GitHub trending page."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ GitHub trending fetch failed ({url}): {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    repos = []

    # GitHub trending uses <article class="Box-row"> for each repo
    articles = soup.select("article.Box-row")
    for article in articles:
        # Repo name: <h2 class="h3"><a href="/owner/name">
        h2 = article.select_one("h2 a")
        if not h2:
            continue
        repo_path = h2.get("href", "").strip("/")
        repo_name = repo_path.split("/")[-1] if "/" in repo_path else repo_path
        repo_url = f"https://github.com/{repo_path}"

        # Description
        desc_el = article.select_one("p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        # Language
        lang_el = article.select_one('[itemprop="programmingLanguage"]')
        language = lang_el.get_text(strip=True) if lang_el else ""
        if not language:
            # Fallback: look for the language color blob
            lang_span = article.select_one("span.d-inline-block.ml-0.mr-3")
            if lang_span:
                language = lang_span.get_text(strip=True)

        # Stars (total)
        stars = 0
        star_links = article.select("a.Link--muted.d-inline-block.mr-3")
        for sl in star_links:
            if "stargazers" in sl.get("href", ""):
                star_text = sl.get_text(strip=True).replace(",", "")
                try:
                    stars = int(star_text)
                except ValueError:
                    pass
                break

        # Today's stars
        today_stars = 0
        today_el = article.select_one("span.d-inline-block.float-sm-right")
        if today_el:
            match = re.search(r"([\d,]+)\s*stars?\s*today", today_el.get_text(), re.IGNORECASE)
            if match:
                try:
                    today_stars = int(match.group(1).replace(",", ""))
                except ValueError:
                    pass

        # Built by (contributors)
        contributors = []
        for img in article.select("a img.avatar"):
            contributors.append(img.get("alt", "").lstrip("@"))

        repos.append({
            "title": f"{repo_path} — {description[:80]}" if description else repo_path,
            "url": repo_url,
            "source": "github_trending",
            "description": description,
            "industry": [language] if language else [],
            "published_at": datetime.utcnow().isoformat() + "Z",
            "metadata": {
                "repo_name": repo_name,
                "full_name": repo_path,
                "language": language,
                "stars": stars,
                "today_stars": today_stars,
                "contributors": contributors[:5],
            },
        })

    return repos


def fetch_latest() -> list[dict]:
    """Fetch trending repos from GitHub across multiple languages.

    Returns:
        List of dicts with title, url, source, description, industry,
        published_at, metadata.
    """
    all_repos = []
    seen = set()

    for url in TRENDING_URLS:
        repos = _parse_trending_page(url)
        for repo in repos:
            repo_url = repo["url"]
            if repo_url not in seen:
                seen.add(repo_url)
                all_repos.append(repo)

    # Sort by today's stars descending
    all_repos.sort(
        key=lambda x: x.get("metadata", {}).get("today_stars", 0),
        reverse=True,
    )

    return all_repos[:50]


if __name__ == "__main__":
    items = fetch_latest()
    print(f"Fetched {len(items)} trending repos\n")
    for item in items[:10]:
        meta = item.get("metadata", {})
        lang = meta.get("language", "?")
        stars = meta.get("stars", 0)
        today = meta.get("today_stars", 0)
        print(f"⭐ {meta['full_name']}  ({lang}) — {stars} total, +{today} today")
        print(f"   {item['description'][:80]}")
        print()
