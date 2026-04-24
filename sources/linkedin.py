"""LinkedIn Scraper — finds similar profiles/companies via LinkedIn profile URLs.

API: linkedin-api8 (RapidAPI)
Endpoint: https://linkedin-api8.p.rapidapi.com/similar-profiles
Quota: 50 credits/month, 70 requests/month
Status: ⚠️ SERVICE DISABLED — returns "We are no longer providing this service"

Use for: Discovering similar companies/people based on a LinkedIn profile URL.
This is a Tier 2 quota-based source. Guard quota aggressively.
"""

import logging
import time
from typing import Optional

import requests

# API Configuration
RAPIDAPI_HOST = "linkedin-api8.p.rapidapi.com"
RAPIDAPI_KEY = "59351167bemsh69cb04174744b16p1959cdjsn9e952846fbf3"
BASE_URL = f"https://{RAPIDAPI_HOST}/similar-profiles"

# Rate limit guard
# 70 requests/month — very tight. Cache everything aggressively.
class LinkedInRateGuard:
    """Tracks LinkedIn API calls to stay within monthly quota."""

    def __init__(self, max_calls: int = 70, window_seconds: int = 30 * 24 * 3600):
        self.max_calls = max_calls
        self.window = window_seconds
        self.calls: list[float] = []

    def can_call(self) -> bool:
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.window]
        return len(self.calls) < self.max_calls

    def record_call(self) -> None:
        self.calls.append(time.time())

    def remaining(self) -> int:
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.window]
        return max(0, self.max_calls - len(self.calls))

    def assert_can_call(self) -> None:
        if not self.can_call():
            raise QuotaExhaustedError(
                f"LinkedIn scraper quota exhausted. "
                f"{self.remaining()} calls remaining. Wait for quota reset."
            )


class QuotaExhaustedError(Exception):
    pass


class ServiceDisabledError(Exception):
    pass


class APIError(Exception):
    pass


# Global guard instance — reuse across calls
_linkedin_guard = LinkedInRateGuard()


def fetch_similar_profiles(
    linkedin_url: str,
    use_cache: bool = True,
    cache_ttl_seconds: int = 7 * 24 * 3600,
) -> list[dict]:
    """Fetch profiles similar to a given LinkedIn profile URL.

    Args:
        linkedin_url: LinkedIn profile URL (person or company).
                      e.g. "https://www.linkedin.com/in/bad神" or
                           "https://www.linkedin.com/company/google"
        use_cache: If False, ignore cache and make a live API call.
        cache_ttl_seconds: How long to cache results (default 7 days).

    Returns:
        List of similar profiles:
        [{
            "name": str,
            "headline": str,
            "location": str,
            "industry": str,
            "profile_url": str,
            "connections": str,
            "source_url": str,  # the URL we queried
        }]

    Raises:
        QuotaExhaustedError: Monthly quota (70 calls) exhausted.
        ServiceDisabledError: API service is disabled.
        APIError: Unexpected error from the API.
    """
    global _linkedin_guard

    # Validate input
    if not linkedin_url or "linkedin.com" not in linkedin_url.lower():
        raise ValueError(f"Invalid LinkedIn URL: {linkedin_url}")

    # Check quota
    _linkedin_guard.assert_can_call()

    # TODO: Implement file-based cache with TTL
    # For now, cache is disabled since the service is down
    if use_cache:
        cached = _get_cached(linkedin_url)
        if cached is not None:
            logging.info(f"[LinkedIn] Cache hit for {linkedin_url}")
            return cached

    # Make API call
    _linkedin_guard.record_call()

    try:
        headers = {
            "x-rapidapi-host": RAPIDAPI_HOST,
            "x-rapidapi-key": RAPIDAPI_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Extract username/path from URL for the API
        # API expects: {"username": "ben-park-1b4b8a15"} or similar
        username = _extract_username(linkedin_url)

        payload = {"username": username}

        response = requests.get(
            BASE_URL,
            headers=headers,
            params=payload,
            timeout=15,
        )

        # Check for service disabled message
        response_text = response.text
        if "no longer providing this service" in response_text.lower():
            raise ServiceDisabledError(
                "LinkedIn scraper API is disabled. "
                "Contact support@professionalnetworkdata.com"
            )

        if response.status_code != 200:
            raise APIError(f"LinkedIn API returned {response.status_code}: {response_text}")

        data = response.json()

        if not data.get("success", True) and data.get("message"):
            raise APIError(f"LinkedIn API error: {data['message']}")

        results = _normalize_response(data, source_url=linkedin_url)

        # Cache results
        if results:
            _set_cached(linkedin_url, results)

        logging.info(
            f"[LinkedIn] fetch_similar_profiles({linkedin_url}) → "
            f"{len(results)} results, {_linkedin_guard.remaining()}/70 calls remaining"
        )

        return results

    except ServiceDisabledError:
        logging.error("[LinkedIn] API service is disabled — not calling again this month")
        raise
    except QuotaExhaustedError:
        raise
    except Exception as e:
        logging.error(f"[LinkedIn] Unexpected error: {e}")
        raise APIError(f"LinkedIn scraper failed: {e}")


def _extract_username(url: str) -> str:
    """Extract the username/slug from a LinkedIn profile URL.

    Examples:
        https://www.linkedin.com/in/bad神 → ben-park-1b4b8a15
        https://www.linkedin.com/company/google → google
    """
    import re

    url = url.strip().rstrip("/")

    # Company URL: /company/name
    if "/company/" in url:
        match = re.search(r"/company/([^/]+)", url)
        if match:
            return match.group(1)

    # Person URL: /in/username
    match = re.search(r"/in/([^/]+)", url)
    if match:
        return match.group(1)

    return url


def _normalize_response(data: dict, source_url: str) -> list[dict]:
    """Normalize the API response into our standard format.

    Expected response shape (if service were active):
    {
        "success": true,
        "data": [
            {
                "profileUrl": "https://www.linkedin.com/in/...",
                "name": "...",
                "headline": "...",
                "location": "...",
                "industry": "...",
                "connections": "...",
            }
        ]
    }
    """
    results = []

    # The actual response shape is unknown — log it for debugging
    if not data.get("data"):
        return results

    profiles = data.get("data", [])
    if not isinstance(profiles, list):
        profiles = [profiles]

    for profile in profiles:
        results.append({
            "name": profile.get("name", ""),
            "headline": profile.get("headline", ""),
            "location": profile.get("location", ""),
            "industry": profile.get("industry", ""),
            "profile_url": profile.get("profileUrl", profile.get("profile_url", "")),
            "connections": profile.get("connections", ""),
            "source_url": source_url,
        })

    return results


# ---------------------------------------------------------------------------
# Cache implementation (file-based)
# ---------------------------------------------------------------------------
import json
import os

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache", "linkedin")
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_key(url: str) -> str:
    """Generate a safe cache filename from a URL."""
    import hashlib
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{key}.json")


def _get_cached(url: str) -> Optional[list[dict]]:
    """Return cached result if fresh, else None."""
    cache_file = _cache_key(url)
    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file) as f:
            entry = json.load(f)

        import time
        if time.time() - entry.get("cached_at", 0) > 7 * 24 * 3600:
            return None

        return entry.get("results")
    except Exception:
        return None


def _set_cached(url: str, results: list[dict]) -> None:
    """Write results to cache file."""
    try:
        cache_file = _cache_key(url)
        with open(cache_file, "w") as f:
            json.dump({
                "url": url,
                "cached_at": time.time(),
                "results": results,
            }, f)
    except Exception as e:
        logging.warning(f"[LinkedIn] Cache write failed: {e}")


# ---------------------------------------------------------------------------
# Public utilities
# ---------------------------------------------------------------------------

def get_quota_status() -> dict:
    """Return current quota usage."""
    global _linkedin_guard
    return {
        "remaining": _linkedin_guard.remaining(),
        "max": _linkedin_guard.max_calls,
        "window_seconds": _linkedin_guard.window,
    }


def suggest_similar_companies(
    company_linkedin_url: str,
    top_n: int = 5,
) -> list[dict]:
    """Find similar companies given a company's LinkedIn page.

    Convenience wrapper around fetch_similar_profiles for companies.

    Args:
        company_linkedin_url: e.g. "https://www.linkedin.com/company/vercel"
        top_n: Return only top N results.

    Returns:
        [{name, headline, location, industry, profile_url}]
    """
    results = fetch_similar_profiles(company_linkedin_url)
    return results[:top_n]


def suggest_similar_people(
    person_linkedin_url: str,
    top_n: int = 5,
) -> list[dict]:
    """Find similar people given a person's LinkedIn profile.

    Convenience wrapper around fetch_similar_profiles for individuals.

    Args:
        person_linkedin_url: e.g. "https://www.linkedin.com/in/bad神"
        top_n: Return only top N results.

    Returns:
        [{name, headline, location, industry, profile_url}]
    """
    results = fetch_similar_profiles(person_linkedin_url)
    return results[:top_n]
