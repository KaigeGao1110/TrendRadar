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
FALLBACK_MODELS = [
    "openai/gpt-oss-120b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-31b-it:free",
]
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


def _is_homepage_only(url: str, name: str) -> bool:
    """Check if URL looks like a generic homepage (low info value)."""
    cleaned = clean_company_name(name).lower()
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.lower()
    # Company homepage typically has minimal path segments
    if path == "/" or path == "":
        # Check if domain name roughly matches company name (not a directory site)
        domain_words = domain.split(".")
        return len([w for w in domain_words if len(w) > 3]) <= 2
    return False


def search_company_specialized(name: str, strategy: str = "crunchbase") -> list[dict]:
    """Run specialized search queries to find more specific company info.

    Args:
        name: Company name.
        strategy: 'crunchbase' (site:crunchbase.com OR site:linkedin.com) or
                  'executive' (company + CEO/founded/series).
    Returns:
        List of up to 3 result dicts.
    """
    cleaned = clean_company_name(name)
    results: list[dict] = []

    if strategy == "crunchbase":
        queries = [
            f'{cleaned} site:crunchbase.com company',
            f'{cleaned} site:linkedin.com company',
        ]
    else:
        queries = [
            f"{cleaned} company CEO founded",
            f"{cleaned} company series funding",
            f'"{cleaned}" startup about',
        ]

    for q in queries:
        # Try DDG first, then Google
        ddg = _search_ddg(q)
        if ddg:
            results.extend(ddg)
        if len(results) >= 3:
            break
        google = _search_google(q)
        if google:
            results.extend(google)
        if len(results) >= 3:
            break

    # Dedupe by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for r in results:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
    return unique[:3]


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


def _try_parse_json_response(content: str) -> Optional[dict]:
    """Parse JSON from LLM response with multiple fallback strategies.

    Handles: markdown code blocks, partial JSON objects, common format errors.
    Returns None only if description field is missing (critical field).
    """
    if not content:
        return None

    content = content.strip()

    # Strip markdown code fences
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    # Strategy 1: try direct JSON parse
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy 2: extract first {...} block
    json_match = re.search(r"\{[\s\S]*\}", content, re.DOTALL)
    if not json_match:
        return None
    candidate = json_match.group(0)

    # Strategy 3: fix common JSON errors
    # Remove trailing commas before closing braces/brackets
    candidate = re.sub(r",\s*([\]}])", r"\1", candidate)
    # Replace single quotes with double quotes (common LLM mistake)
    candidate = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', candidate)
    try:
        parsed = json.loads(candidate)
        # Must have at least description to be useful
        if parsed.get("description"):
            return parsed
        return None
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy 4: try raw candidate even without fixes
    try:
        parsed = json.loads(candidate)
        if parsed.get("description"):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def _enrich_with_model_selector(name: str, text: str) -> dict:
    """Extract company info using the smart model selector."""
    from analyzer.model_selector import call_openrouter

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
        result = call_openrouter(prompt, "sec_enrichment", max_tokens=500, temperature=0.3)
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _try_parse_json_response(content)
        if parsed is not None:
            return {
                "description": parsed.get("description"),
                "primary_sector": parsed.get("primary_sector"),
                "sub_sector": parsed.get("sub_sector"),
                "target_customer": parsed.get("target_customer"),
                "business_model": parsed.get("business_model"),
                "main_product": parsed.get("main_product"),
                "website": parsed.get("website"),
            }
    except Exception as e:
        print(f"Model selector failed for '{name}': {e}")

    return _empty_extraction()


def _enrich_with_deepseek(name: str, text: str) -> dict:
    """Extract company info using DeepSeek V4 Flash."""
    import requests as _req

    # Load DEEPSEEK_API_KEY from openclaw config
    ds_key = os.environ.get("DEEPSEEK_API_KEY")
    if not ds_key:
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                _cfg = json.load(f)
            ds_key = _cfg.get("env", {}).get("DEEPSEEK_API_KEY")
    if not ds_key:
        print(f"DEEPSEEK_API_KEY not found, falling back to model selector for '{name}'")
        return _enrich_with_model_selector(name, text)

    prompt = (
        f'Given this text about "{name}", extract JSON with:\n'
        f"  description: one sentence describing what the company does\n"
        f"  primary_sector: broad category (DevOps, Healthcare, Finance, Education, Logistics, Manufacturing, Media, Energy, Real Estate, Agriculture, Defense, Construction, Retail, Food, Gaming, Legal, Travel, Other)\n"
        f"  sub_sector: specific niche within that sector\n"
        f"  target_customer: who buys this product/service (developers, enterprises, SMBs, consumers, hospitals, government, etc.)\n"
        f"  business_model: how they make money (SaaS subscription, marketplace, hardware sales, consulting, licensing, advertising, etc.)\n"
        f"  main_product: name of core product/service if mentioned\n"
        f"  website: homepage URL if available\n\n"
        f'Return ONLY valid JSON, no markdown, no explanation.\n\n'
        f"Text:\n{text[:2500]}"
    )

    try:
        resp = _req.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {ds_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _try_parse_json_response(content)
        if parsed is not None:
            return {
                "description": parsed.get("description"),
                "primary_sector": parsed.get("primary_sector"),
                "sub_sector": parsed.get("sub_sector"),
                "target_customer": parsed.get("target_customer"),
                "business_model": parsed.get("business_model"),
                "main_product": parsed.get("main_product"),
                "website": parsed.get("website"),
            }
    except Exception as e:
        print(f"DeepSeek failed for '{name}': {e}, falling back to model selector")
        return _enrich_with_model_selector(name, text)

    return _empty_extraction()


def extract_company_info(name: str, text: str) -> dict:
    """Extract company info from text using DeepSeek V4 Flash.

    Args:
        name: Company name.
        text: Text content about the company.

    Returns:
        Dict with keys: description, primary_sector, sub_sector, target_customer,
        business_model, main_product, website.
        Values may be None if extraction fails.
    """
    return _enrich_with_deepseek(name, text)


def _empty_extraction() -> dict:
    return {
        "description": None,
        "primary_sector": None,
        "sub_sector": None,
        "target_customer": None,
        "business_model": None,
        "main_product": None,
        "website": None,
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

    # Step 2: Fetch all results and pick the one with the most text
    # (some results return minimal CSS/JS from single-page apps)
    best_text = ""
    best_url = ""
    for sr in search_results:
        url = sr.get("url", "")
        text = fetch_company_page(url)
        if text and len(text) > len(best_text):
            best_text = text
            best_url = url

    if not best_text or len(best_text) < 300:
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


def reenrich_low_quality(name: str, previous_result: dict) -> dict:
    """Re-run enrichment on a previously low-quality result using fallback strategies.

    Specifically targets extraction_failed cases by retrying with more robust
    model fallback and specialized search queries.

    Args:
        name: Company name.
        previous_result: Result dict from a prior enrich_company call.

    Returns:
        Updated enrichment result (same schema as enrich_company).
    """
    if previous_result.get("quality_reason") not in ("extraction_failed", "partial_info"):
        return previous_result

    normalized = normalize_name(name)
    result = dict(previous_result)
    result["normalized_name"] = normalized
    result["entity_name"] = name

    # Try specialized search first if we had no search results
    search_results: list[dict] = []
    if previous_result.get("quality_reason") == "extraction_failed":
        # Try crunchbase/linkedin focused search
        specialized = search_company_specialized(name, "crunchbase")
        if specialized:
            search_results = specialized
        else:
            search_results = search_company(name)

        if not search_results:
            result["quality_reason"] = "no_search_results"
            return result

        # Fetch best result
        MIN_TEXT_LEN = 300
        best_text = ""
        best_url = ""
        for sr in search_results:
            url = sr.get("url", "")
            text = fetch_company_page(url)
            if text and len(text) >= MIN_TEXT_LEN:
                best_text = text
                best_url = url
                break

        if not best_text:
            result["quality_reason"] = "page_fetch_failed"
            return result

        # Re-extract with fallback models
        extracted = extract_company_info(name, best_text)

        result["description"] = extracted.get("description")
        result["primary_sector"] = extracted.get("primary_sector")
        result["sub_sector"] = extracted.get("sub_sector")
        result["target_customer"] = extracted.get("target_customer")
        result["business_model"] = extracted.get("business_model")
        result["main_product"] = extracted.get("main_product")
        result["website"] = extracted.get("website")
        result["enrichment_source"] = best_url

        # Re-evaluate quality
        has_desc = bool(result["description"])
        has_sector = bool(result.get("primary_sector"))
        has_biz = bool(result.get("business_model"))

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


def backfill_profiles(dry_run: bool = True, limit: Optional[int] = None, workers: int = 4):
    """Backfill primary_sector, sub_sector, target_customer, business_model, main_product.

    For profiles where primary_sector IS NULL, re-run enrichment to extract the missing fields.

    Args:
        dry_run: If True, only print what would be updated without writing to DB.
        limit: Optional max number of profiles to process.
        workers: Number of parallel threads (default 4). I/O-bound so 4-8 is good.
    """
    from storage.sec_local_db import SecLocalDB
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    from datetime import datetime, timezone
    db = SecLocalDB()
    query = "SELECT * FROM sec_company_profiles WHERE primary_sector IS NULL"
    if limit:
        query += f" LIMIT {limit}"
    rows = db.conn.execute(query).fetchall()
    profiles = [dict(r) for r in rows]

    if not profiles:
        print("No profiles need backfill (all have primary_sector).")
        return

    total = len(profiles)
    print(f"Found {total} profiles needing backfill (dry_run={dry_run}, workers={workers})")

    lock = threading.Lock()
    counter = [0]
    updated = [0]
    errors = [0]
    results_to_write = []
    write_lock = threading.Lock()

    def process_one(args):
        i, profile = args
        name = profile.get("entity_name") or profile.get("normalized_name", "")
        with lock:
            counter[0] += 1
            pos = counter[0]
        print(f"[{pos}/{total}] Processing: {name}", flush=True)
        try:
            result = enrich_company(name)
            update_fields = {
                "primary_sector": result.get("primary_sector"),
                "sub_sector": result.get("sub_sector"),
                "target_customer": result.get("target_customer"),
                "business_model": result.get("business_model"),
                "main_product": result.get("main_product"),
                "description": result.get("description"),
                "enrichment_source": result.get("enrichment_source"),
                "enrichment_quality": result.get("enrichment_quality"),
                "quality_reason": result.get("quality_reason"),
                "enriched_at": datetime.now(timezone.utc).isoformat(),
            }
            if dry_run:
                print(f"  [dry-run] primary_sector={update_fields['primary_sector']}, "
                      f"quality={update_fields['enrichment_quality']}", flush=True)
            else:
                with write_lock:
                    results_to_write.append((profile["normalized_name"], update_fields))
                    updated[0] += 1
        except Exception as e:
            print(f"  [error] {e}", flush=True)
            with lock:
                errors[0] += 1
        time.sleep(0.5)

    args_list = list(enumerate(profiles, 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(process_one, args) for args in args_list]
        for f in as_completed(futures):
            pass

    if not dry_run and results_to_write:
        print(f"\nWriting {len(results_to_write)} results to DB...", flush=True)
        cols = ["primary_sector", "sub_sector", "target_customer", "business_model",
                "main_product", "description", "enrichment_source", "enrichment_quality",
                "quality_reason", "enriched_at"]
        set_clause = ", ".join(f"{c}=?" for c in cols)
        for norm_name, fields in results_to_write:
            vals = [fields[c] for c in cols] + [norm_name]
            db.conn.execute(
                f"UPDATE sec_company_profiles SET {set_clause} WHERE normalized_name=?",
                vals
            )
        db.conn.commit()
        print(f"Wrote {len(results_to_write)} records.", flush=True)

    print(f"\nDone. {'Would update' if dry_run else 'Updated'} {updated[0]}/{total}, errors={errors[0]}")


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
