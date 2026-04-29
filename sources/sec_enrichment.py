"""Company enrichment engine for SEC Form D filings.

Web search + LLM extraction pipeline for enriching company profiles.
"""

import json
import os
import re
import sys
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests

# Add project root to path when running directly
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.expanduser("~/.openclaw/.env"))
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)
    except ImportError:
        pass


OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openai/gpt-oss-120b:free"
DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
TAVILY_API_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT = 30
DDG_REQUEST_DELAY = 2.0  # seconds between DuckDuckGo requests
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Suffixes to strip from company names
NAME_SUFFIXES = [
    r"Holdings Corp\.?",
    r"Holding Corp\.?",
    r"Holdings Inc\.?",
    r"Holding Inc\.?",
    r"Holdings LLC",
    r"Holding LLC",
    r"Holdings Ltd\.?",
    r"Holding Ltd\.?",
    r"Holdings L\.?P\.?",
    r"Holding L\.?P\.?",
    r"Holdings Co\.?",
    r"Holding Co\.?",
    r"Holdings Company",
    r"Holding Company",
    r"Holdings",
    r"Holding",
    r"Corp\.?",
    r"Inc\.?",
    r"LLC",
    r"L\.?P\.?",
    r"Ltd\.?",
    r"Co\.?",
    r"Company",
]


def _get_openrouter_key() -> Optional[str]:
    """Load OpenRouter API key from environment or openclaw config."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key

    # Try loading from openclaw config
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            env = config.get("env", {})
            return env.get("OPENROUTER_API_KEY")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _get_tavily_key() -> Optional[str]:
    """Load Tavily API key from environment or openclaw config."""
    key = os.environ.get("TAVILY_API_KEY")
    if key:
        return key
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            env = config.get("env", {})
            return env.get("TAVILY_API_KEY")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def clean_company_name(name: str) -> str:
    """Remove legal suffixes and clean a company name for search.

    Examples:
        "X.AI Holdings Corp." → "X.AI"
        "Deep Cogito Inc." → "Deep Cogito"
    """
    cleaned = name.strip()
    for suffix in NAME_SUFFIXES:
        pattern = r"\s*,?\s*" + suffix + r"\s*$"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    # Strip trailing punctuation and whitespace
    cleaned = re.sub(r"[\s.,;]+$", "", cleaned)
    return cleaned.strip()


def normalize_name(name: str) -> str:
    """Normalize company name for deduplication key.

    Uppercase, strip whitespace, remove suffixes.
    """
    cleaned = clean_company_name(name)
    return cleaned.upper().strip()


def _search_tavily(query: str) -> list[dict]:
    """Search via Tavily API (free tier: 1000/month)."""
    api_key = _get_tavily_key()
    if not api_key:
        return []
    try:
        resp = requests.post(
            TAVILY_API_URL,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": 3,
                "include_answer": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:200],
            })
        return results
    except Exception as e:
        print(f"Tavily search error: {e}")
        return []


def _search_ddg(query: str) -> list[dict]:
    """Search via DuckDuckGo HTML (free, but rate-limited)."""
    try:
        resp = requests.get(
            DUCKDUCKGO_URL,
            params={"q": query},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"DuckDuckGo search error: {e}")
        return []

    html = resp.text
    results = []

    result_blocks = re.findall(
        r'<div class="result[^"]*"[^>]*>.*?<\/div>\s*<\/div>\s*<\/div>',
        html,
        re.DOTALL,
    )
    if not result_blocks:
        result_blocks = re.findall(
            r'<div class="web-result[^"]*"[^>]*>.*?<\/div>\s*<\/div>\s*<\/div>',
            html,
            re.DOTALL,
        )
    if not result_blocks:
        result_blocks = re.findall(
            r'<div class="result[^"]*"[^>]*>.*?<\/div>\s*(?=<div class="result|<div id="links")',
            html,
            re.DOTALL,
        )

    for block in result_blocks[:3]:
        url_match = re.search(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"',
            block,
        )
        if not url_match:
            url_match = re.search(
                r'<a[^>]+href="([^"]+)"[^>]*class="result__a"',
                block,
            )
        if not url_match:
            url_match = re.search(r'<a[^>]+href="([^"]+)"', block)
        raw_url = url_match.group(1) if url_match else ""

        if "duckduckgo.com/l/" in raw_url:
            parsed = urlparse(raw_url)
            params = parse_qs(parsed.query)
            url = params.get("uddg", [raw_url])[0]
        elif raw_url.startswith("//"):
            url = "https:" + raw_url
        else:
            url = raw_url

        title_match = re.search(
            r'<a[^>]+class="result__a"[^>]*>(.*?)<\/a>',
            block,
            re.DOTALL,
        )
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""

        snippet_match = re.search(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)<\/a>',
            block,
            re.DOTALL,
        )
        snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip() if snippet_match else ""

        if url:
            results.append({"title": title, "url": url, "snippet": snippet})

    return results


def _search_google(query: str) -> list[dict]:
    """Search via Google HTML."""
    try:
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num=5"
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        results = []
        # Parse Google results
        for match in re.finditer(r'<a[^>]+href="/url\?q=([^&"]+)', resp.text):
            href = match.group(1)
            if "google.com" not in href and "youtube.com" not in href:
                results.append({"title": "", "url": href, "snippet": ""})
            if len(results) >= 3:
                break
        return results
    except Exception as e:
        print(f"Google search error: {e}")
        return []


def _search_bing(query: str) -> list[dict]:
    """Search via Bing HTML."""
    try:
        url = f"https://cn.bing.com/search?q={requests.utils.quote(query)}&ensearch=1"
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        results = []
        # Parse Bing results
        for match in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*><h2', resp.text):
            href = match.group(1)
            if "bing.com" not in href and "microsoft.com" not in href:
                results.append({"title": "", "url": href, "snippet": ""})
            if len(results) >= 3:
                break
        # Fallback pattern
        if not results:
            for match in re.finditer(r'<cite>(https?://[^<]+)</cite>', resp.text):
                href = match.group(1)
                results.append({"title": "", "url": href, "snippet": ""})
                if len(results) >= 3:
                    break
        return results
    except Exception as e:
        print(f"Bing search error: {e}")
        return []


def _search_brave(query: str) -> list[dict]:
    """Search via Brave HTML."""
    try:
        url = f"https://search.brave.com/search?q={requests.utils.quote(query)}"
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        results = []
        for match in re.finditer(r'<a[^>]+class="result-header"[^>]+href="([^"]+)"', resp.text):
            href = match.group(1)
            if "brave.com" not in href:
                results.append({"title": "", "url": href, "snippet": ""})
            if len(results) >= 3:
                break
        return results
    except Exception as e:
        print(f"Brave search error: {e}")
        return []


def search_company(name: str) -> list[dict]:
    """Search for a company using multiple free engines with fallback.

    Order: Google → Bing → Brave → DuckDuckGo → Tavily (last resort)

    Args:
        name: Company name to search.

    Returns:
        List of up to 3 result dicts with keys:
        - title: result title
        - url: result URL
        - snippet: result snippet text
    """
    cleaned = clean_company_name(name)
    query = f"{cleaned} company what does it do sector"

    # Try free engines in order
    engines = [
        ("Google", _search_google),
        ("Bing", _search_bing),
        ("Brave", _search_brave),
    ]

    for engine_name, engine_fn in engines:
        time.sleep(1.0)  # Be nice to free engines
        results = engine_fn(query)
        if results:
            return results

    # Last resort: Tavily (limited free tier)
    results = _search_tavily(query)
    if results:
        return results

    return []

    html = resp.text
    results = []

    # Parse DuckDuckGo HTML results
    # Each result is in a .result div
    result_blocks = re.findall(
        r'<div class="result[^"]*"[^>]*>.*?<\/div>\s*<\/div>\s*<\/div>',
        html,
        re.DOTALL,
    )
    if not result_blocks:
        # Fallback: try simpler pattern
        result_blocks = re.findall(
            r'<div class="web-result[^"]*"[^>]*>.*?<\/div>\s*<\/div>\s*<\/div>',
            html,
            re.DOTALL,
        )
    if not result_blocks:
        # Even simpler fallback
        result_blocks = re.findall(
            r'<div class="result[^"]*"[^>]*>.*?<\/div>\s*(?=<div class="result|<div id="links")',
            html,
            re.DOTALL,
        )

    for block in result_blocks[:3]:
        # Extract URL
        url_match = re.search(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"',
            block,
        )
        if not url_match:
            url_match = re.search(
                r'<a[^>]+href="([^"]+)"[^>]*class="result__a"',
                block,
            )
        if not url_match:
            url_match = re.search(r'<a[^>]+href="([^"]+)"', block)
        url = url_match.group(1) if url_match else ""

        # DuckDuckGo uses redirect URLs - extract actual URL
        if "duckduckgo.com/l/" in url:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            url = params.get("uddg", [url])[0]
        elif url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://duckduckgo.com" + url

        # Extract title
        title_match = re.search(
            r'<a[^>]+class="result__a"[^>]*>(.*?)<\/a>',
            block,
            re.DOTALL,
        )
        if not title_match:
            title_match = re.search(r'<a[^>]*>(.*?)<\/a>', block, re.DOTALL)
        title = _strip_html_tags(title_match.group(1)) if title_match else ""

        # Extract snippet
        snippet_match = re.search(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)<\/a>',
            block,
            re.DOTALL,
        )
        if not snippet_match:
            snippet_match = re.search(
                r'<div[^>]+class="result__snippet"[^>]*>(.*?)<\/div>',
                block,
                re.DOTALL,
            )
        if not snippet_match:
            # Try any div after the title link
            snippet_match = re.search(
                r'<\/a>\s*<div[^>]*>(.*?)<\/div>',
                block,
                re.DOTALL,
            )
        snippet = _strip_html_tags(snippet_match.group(1)) if snippet_match else ""

        if url and title:
            results.append({
                "title": title.strip(),
                "url": url.strip(),
                "snippet": snippet.strip(),
            })

    return results


def _strip_html_tags(html: str) -> str:
    """Remove HTML tags from a string."""
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_company_page(url: str) -> str:
    """Fetch a web page and extract text content.

    Args:
        url: URL to fetch.

    Returns:
        Plain text content (max 3000 chars), or empty string on error.
    """
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Fetch error for {url}: {e}")
        return ""

    text = _strip_html_tags(resp.text)
    # Truncate to max 3000 chars
    return text[:3000]


def extract_company_info(name: str, text: str) -> dict:
    """Extract company info from text using OpenRouter LLM.

    Args:
        name: Company name.
        text: Text content about the company.

    Returns:
        Dict with keys: description, sector, main_business, website.
        Values may be None if extraction fails.
    """
    api_key = _get_openrouter_key()
    if not api_key:
        print("OpenRouter API key not found")
        return {
            "description": None,
            "sector": None,
            "main_business": None,
            "website": None,
        }

    prompt = (
        f'Given this text about "{name}", extract JSON with:\n'
        f"  description: one sentence describing what the company does\n"
        f"  sector: classify into a sector (free text, suggest: AI/ML, Fintech, "
        f"HealthTech, BioTech, EdTech, DevOps/Infra, Cybersecurity, E-commerce, "
        f"SaaS, ClimateTech, AgTech, Robotics, Autonomous, Gaming, Media, "
        f"RealEstateTech, LegalTech, HRTech, FoodTech, SpaceTech, Defense, "
        f"Blockchain/Web3, Hardware, Semiconductor, Biopharma, MedicalDevices, "
        f"InsurTech, ConstructionTech, Logistics, Finance, Energy, Manufacturing, Other)\n"
        f"  main_business: what they sell/build/do\n"
        f"  website: homepage URL\n\n"
        f'Return ONLY valid JSON: {{"description": "...", "sector": "...", '
        f'"main_business": "...", "website": "..."}}\n\n'
        f"Text:\n{text[:2500]}"
    )

    try:
        resp = requests.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"OpenRouter API error for '{name}': {e}")
        return {
            "description": None,
            "sector": None,
            "main_business": None,
            "website": None,
        }

    try:
        data = resp.json()
        if "choices" not in data:
            print(f"LLM unexpected response for '{name}': {json.dumps(data)[:200]}")
            return {"description": None, "sector": None, "main_business": None, "website": None}

        choice = data["choices"][0]
        content = choice.get("message", {}).get("content")
        if not content:
            content = choice.get("text") or choice.get("delta", {}).get("content")
        if not content:
            print(f"LLM empty content for '{name}'")
            return {"description": None, "sector": None, "main_business": None, "website": None}

        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
        # Try to extract JSON from response
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)
        parsed = json.loads(content)
    except (KeyError, json.JSONDecodeError, TypeError) as e:
        print(f"LLM response parse error for '{name}': {e}")
        return {"description": None, "sector": None, "main_business": None, "website": None}

    return {
        "description": parsed.get("description"),
        "sector": parsed.get("sector"),
        "main_business": parsed.get("main_business"),
        "website": parsed.get("website"),
    }


def enrich_company(name: str) -> dict:
    """Run the full enrichment pipeline for a company.

    Args:
        name: Original company name.

    Returns:
        Enrichment result dict with keys:
        - normalized_name: dedup key
        - entity_name: original name
        - description: one sentence description
        - sector: classified sector
        - main_business: what they do
        - website: homepage URL
        - enrichment_source: source of data
        - enrichment_quality: high/medium/low
    """
    normalized = normalize_name(name)
    result = {
        "normalized_name": normalized,
        "entity_name": name,
        "description": None,
        "sector": None,
        "main_business": None,
        "website": None,
        "enrichment_source": None,
        "enrichment_quality": "low",
    }

    # Step 1: Search
    search_results = search_company(name)
    if not search_results:
        return result

    # Step 2: Fetch best result (prefer company website over directories)
    best_text = ""
    best_url = ""
    for sr in search_results:
        url = sr.get("url", "")
        text = fetch_company_page(url)
        if text:
            best_text = text
            best_url = url
            break

    if not best_text:
        return result

    # Step 3: Extract info via LLM
    extracted = extract_company_info(name, best_text)

    result["description"] = extracted.get("description")
    result["sector"] = extracted.get("sector")
    result["main_business"] = extracted.get("main_business")
    result["website"] = extracted.get("website")
    result["enrichment_source"] = best_url

    # Determine quality
    has_desc = bool(result["description"])
    has_sector = bool(result["sector"])
    has_biz = bool(result["main_business"])
    if has_desc and has_sector and has_biz:
        result["enrichment_quality"] = "high"
    elif has_desc or has_sector:
        result["enrichment_quality"] = "medium"
    else:
        result["enrichment_quality"] = "low"

    return result


if __name__ == "__main__":
    # Quick test
    test_name = "Deep Cogito Inc."
    print(f"Testing enrichment for: {test_name}")
    print(f"Cleaned: {clean_company_name(test_name)}")
    print(f"Normalized: {normalize_name(test_name)}")
    print("Searching...")
    results = search_company(test_name)
    print(f"Found {len(results)} search results")
    for r in results:
        print(f"  - {r['title']}: {r['url']}")
    if results:
        enriched = enrich_company(test_name)
        print(f"Enriched: {json.dumps(enriched, indent=2)}")
