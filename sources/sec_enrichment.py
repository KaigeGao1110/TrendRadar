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
DUCKDUCKGO_URL = "https://lite.duckduckgo.com/lite/"
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
    """Search via DuckDuckGo Lite (text-based, free, no JS required)."""
    try:
        resp = requests.get(
            DUCKDUCKGO_URL,
            params={"q": query},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"DuckDuckGo search error: {e}")
        return []

    results = []
    # DuckDuckGo Lite uses <a rel="nofollow" href="//duckduckgo.com/l/?uddg=...">text</a>
    links = re.findall(
        r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        resp.text,
        re.DOTALL,
    )
    for raw_url, title_html in links[:3]:
        # Extract actual URL from DDG redirect
        if "duckduckgo.com/l/" in raw_url:
            parsed = urlparse(raw_url)
            params = parse_qs(parsed.query)
            url = params.get("uddg", [raw_url])[0]
        elif raw_url.startswith("//"):
            url = "https:" + raw_url
        else:
            url = raw_url

        title = re.sub(r"<[^>]+>", "", title_html).strip()
        if url and "duckduckgo.com" not in url:
            results.append({"title": title, "url": url, "snippet": ""})

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

    Order: DDG Lite → Google → Bing → Brave → Tavily (last resort)

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

    # Sequential with fallback: try each engine in order
    all_results: list[dict] = []
    sources_used: list[str] = []

    # DDG Lite (free, unlimited) - try first
    ddg = _search_ddg(query)
    if ddg:
        all_results.extend(ddg)
        sources_used.append("DDG")

    # Google HTML
    google = _search_google(query)
    if google:
        all_results.extend(google)
        sources_used.append("Google")

    # Bing HTML
    bing = _search_bing(query)
    if bing:
        all_results.extend(bing)
        sources_used.append("Bing")

    # Brave HTML
    brave = _search_brave(query)
    if brave:
        all_results.extend(brave)
        sources_used.append("Brave")

    # Tavily (1000 free/month, AI-structured) - fallback
    tavily = _search_tavily(query)
    if tavily:
        all_results.extend(tavily)
        sources_used.append("Tavily")

    # Dedupe by URL, keep unique results
    seen_urls: set[str] = set()
    unique_results: list[dict] = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(r)

    # Return top 5 unique results
    if unique_results:
        print(f"Search: {sources_used} → {len(unique_results)} unique results")
        return unique_results[:5]

    return []


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
            "primary_sector": None,
            "sub_sector": None,
            "target_customer": None,
            "business_model": None,
            "main_product": None,
            "website": None,
        }

    prompt = (
        f'Given this text about "{name}", extract JSON with:\n'
        f"  description: one sentence describing what the company does\n"
        f"  primary_sector: broad category (DevOps, Healthcare, Finance, Education, Logistics, Manufacturing, Media, Energy, Real Estate, Agriculture, Defense, Construction, Retail, Food, Gaming, Legal, Travel, Other)\n"
        f"  sub_sector: specific niche within that sector (e.g., Frontend Deployment, Cancer Therapeutics, Payment Processing, AI Code Generation, Robot-Assisted Surgery)\n"
        f"  target_customer: who buys this product/service (developers, enterprises, SMBs, consumers, hospitals, government, etc.)\n"
        f"  business_model: how they make money (SaaS subscription, marketplace, hardware sales, consulting, licensing, advertising, etc.)\n"
        f"  main_product: name of core product/service if mentioned\n"
        f"  website: homepage URL if available\n\n"
        f'Return ONLY valid JSON, no markdown, no explanation.\n\n'
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
            "primary_sector": None,
            "sub_sector": None,
            "target_customer": None,
            "business_model": None,
            "main_product": None,
            "website": None,
        }

    try:
        data = resp.json()
        if "choices" not in data:
            print(f"LLM unexpected response for '{name}': {json.dumps(data)[:200]}")
            return {"description": None, "primary_sector": None, "sub_sector": None, "target_customer": None, "business_model": None, "main_product": None, "website": None}

        choice = data["choices"][0]
        content = choice.get("message", {}).get("content")
        if not content:
            content = choice.get("text") or choice.get("delta", {}).get("content")
        if not content:
            print(f"LLM empty content for '{name}'")
            return {"description": None, "primary_sector": None, "sub_sector": None, "target_customer": None, "business_model": None, "main_product": None, "website": None}

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
        return {"description": None, "primary_sector": None, "sub_sector": None, "target_customer": None, "business_model": None, "main_product": None, "website": None}

    return {
        "description": parsed.get("description"),
        "primary_sector": parsed.get("primary_sector"),
        "sub_sector": parsed.get("sub_sector"),
        "target_customer": parsed.get("target_customer"),
        "business_model": parsed.get("business_model"),
        "main_product": parsed.get("main_product"),
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
        - primary_sector: broad sector category
        - sub_sector: specific niche
        - target_customer: who buys the product
        - business_model: how they make money
        - main_product: core product name
        - website: homepage URL
        - enrichment_source: source of data
        - enrichment_quality: high/medium/low
        - quality_reason: no_search_results/page_fetch_failed/extraction_failed/partial_info
    """
    normalized = normalize_name(name)
    result = {
        "normalized_name": normalized,
        "entity_name": name,
        "description": None,
        "primary_sector": None,
        "sub_sector": None,
        "target_customer": None,
        "business_model": None,
        "main_product": None,
        "website": None,
        "enrichment_source": None,
        "enrichment_quality": "low",
        "quality_reason": None,
    }

    # Step 1: Search
    search_results = search_company(name)
    if not search_results:
        result["quality_reason"] = "no_search_results"
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
        result["quality_reason"] = "page_fetch_failed"
        return result

    # Step 3: Extract info via LLM
    extracted = extract_company_info(name, best_text)

    result["description"] = extracted.get("description")
    result["primary_sector"] = extracted.get("primary_sector")
    result["sub_sector"] = extracted.get("sub_sector")
    result["target_customer"] = extracted.get("target_customer")
    result["business_model"] = extracted.get("business_model")
    result["main_product"] = extracted.get("main_product")
    result["website"] = extracted.get("website")
    result["enrichment_source"] = best_url

    # Determine quality and reason
    has_desc = bool(result["description"])
    has_sector = bool(result.get("primary_sector"))
    has_sub = bool(result.get("sub_sector"))
    has_biz = bool(result.get("business_model"))
    has_product = bool(result.get("main_product"))

    if has_desc and has_sector and has_biz:
        result["enrichment_quality"] = "high"
        result["quality_reason"] = None
    elif has_desc or has_sector:
        result["enrichment_quality"] = "medium"
        result["quality_reason"] = "partial_info"
    else:
        result["enrichment_quality"] = "low"
        result["quality_reason"] = "extraction_failed"

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
