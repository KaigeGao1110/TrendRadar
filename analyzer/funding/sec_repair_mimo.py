#!/usr/bin/env python3
"""Repair low-quality enrichments using MiMo Web Search.

MiMo handles both search and extraction in one API call, bypassing
our web_fetch + LLM extraction flow that fails on many sites.
"""
import os
import sys
import json
import requests
import re
from dotenv import load_dotenv
from urllib.parse import urlparse

# Load env
load_dotenv(os.path.expanduser("~/.openclaw/.env"))
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"), override=True)

MIMO_API_URL = "https://api.xiaomimimo.com/v1/chat/completions"
MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not all([MIMO_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    print("Missing required env vars")
    sys.exit(1)


def get_low_quality_profiles(limit: int = None) -> list[dict]:
    """Fetch low-quality profiles from Supabase."""
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    all_profiles = []
    offset = 0
    page_size = 1000
    while True:
        query = client.table("sec_company_profiles").select(
            "id,normalized_name,entity_name,enrichment_source"
        ).eq("enrichment_quality", "low")
        if limit:
            query = query.limit(limit)
        result = query.range(offset, offset + page_size - 1).execute()
        batch = result.data or []
        all_profiles.extend(batch)
        if len(batch) < page_size or limit:
            break
        offset += page_size
    return all_profiles


def repair_with_mimo(entity_name: str, existing_source: str = None) -> dict:
    """Use MiMo to search and extract company info."""
    try:
        # Use existing source as hint if available
        context = ""
        if existing_source:
            domain = urlparse(existing_source).netloc
            if domain and "companiesbio" not in domain and "bizapedia" not in domain:
                context = f" (check {existing_source})"
        
        prompt = f"""Find comprehensive information about this company and extract:
1. Company description (1-2 sentences, what they do)
2. Industry sector (choose ONE: AI/ML, Fintech, HealthTech, SaaS, BioTech, ClimateTech, Energy, FoodTech, Manufacturing, RealEstateTech, Cybersecurity, Media, Finance, Biopharma, SpaceTech, Other)
3. Main business/product (1 sentence)
4. Company website URL

Company: {entity_name}{context}

Return ONLY valid JSON: {"description": "...", "sector": "...", "main_business": "...", "website": "..."}"""

        resp = requests.post(
            MIMO_API_URL,
            headers={
                "api-key": MIMO_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "model": "mimo-v2-flash",
                "messages": [{"role": "user", "content": prompt}],
                "tools": [{
                    "type": "web_search",
                    "max_keyword": 2,
                    "force_search": True,
                    "limit": 2,
                }],
                "max_completion_tokens": 400,
                "temperature": 0.3,
            },
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        
        # Parse JSON
        try:
            extracted = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON block
            match = re.search(r'\{[^{}]+\}', content)
            if match:
                extracted = json.loads(match.group())
            else:
                return {}
        
        # Get best source URL
        annotations = data["choices"][0]["message"].get("annotations", [])
        best_source = annotations[0].get("url") if annotations else existing_source
        
        return {
            "description": extracted.get("description"),
            "sector": extracted.get("sector"),
            "main_business": extracted.get("main_business"),
            "website": extracted.get("website"),
            "enrichment_source": best_source,
            "enrichment_quality": "high" if extracted.get("sector") else "medium",
        }
    except Exception as e:
        print(f"MiMo error for '{entity_name}': {e}")
        return {}


def update_profile(client, profile_id: str, updates: dict) -> bool:
    """Update profile in Supabase."""
    try:
        client.table("sec_company_profiles").update(updates).eq("id", profile_id).execute()
        return True
    except Exception as e:
        print(f"Update error: {e}")
        return False


def main():
    print("Fetching low-quality profiles...")
    profiles = get_low_quality_profiles()
    print(f"Found {len(profiles)} low-quality profiles")
    
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    repaired = 0
    failed = 0
    
    for i, p in enumerate(profiles, 1):
        entity_name = p["entity_name"]
        print(f"[{i}/{len(profiles)}] Repairing: {entity_name}")
        
        result = repair_with_mimo(entity_name, p.get("enrichment_source"))
        
        if result and result.get("sector"):
            if update_profile(client, p["id"], result):
                repaired += 1
                print(f"  ✓ {result['sector']}")
            else:
                failed += 1
        else:
            failed += 1
            print(f"  ✗ No data extracted")
    
    print(f"\nRepair complete: {repaired} repaired, {failed} failed")


if __name__ == "__main__":
    main()
