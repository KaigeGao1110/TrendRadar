"""RSS Pain Extractor — extract pain signals from newsletter content using Xiaomi MiMo v2.5.

Fetches RSS newsletters and uses MiMo v2.5 to identify pain points,
frustrations, and unmet needs mentioned in the content.
"""

import os
import re
import json
import requests
from datetime import datetime
from sources.rss import fetch_all_newsletters, NEWSLETTERS

REQUEST_TIMEOUT = 30


def _get_mimo_key() -> str:
    """Get MIMO API key from env or openclaw config."""
    key = os.environ.get("MIMO_API_KEY", "")
    if not key:
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                _cfg = json.load(f)
            key = _cfg.get("env", {}).get("MIMO_API_KEY", "")
    return key


def extract_pains_from_text(text: str, source: str = "") -> list[dict]:
    """Use MiMo v2.5 to extract pain signals from text.
    
    Args:
        text: Newsletter content to analyze
        source: Source name (e.g. "TLDR", "a16z")
    
    Returns:
        List of pain signals: [{pain, context, severity, category}]
    """
    prompt = f"""Analyze this newsletter content and extract pain points, frustrations,
and unmet needs. Focus on:
- Tools/software that people complain about
- Processes that are described as broken or slow
- Industries with known problems
- Unmet needs that could be opportunities

Source: {source}
Content: {text[:2000]}

Return JSON array of pain signals (max 5):
[{{"pain": "description of the pain point", "context": "where/how it was mentioned",
   "severity": "high/medium/low", "category": "industry or topic"}}]

Return ONLY valid JSON array. If no pain signals found, return empty array [].
"""

    mimo_key = _get_mimo_key()
    try:
        if mimo_key:
            resp = requests.post(
                "https://api.xiaomimimo.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {mimo_key}"},
                json={
                    "model": "mimo-v2.5",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.3,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        else:
            # Fallback to OpenRouter
            from analyzer.model_selector import call_openrouter
            result = call_openrouter(prompt, "rss_pain_extraction", max_tokens=500, temperature=0.3)
            content = result["choices"][0]["message"]["content"]
        
        # Parse JSON
        try:
            pains = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON block
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                pains = json.loads(match.group())
            else:
                pains = []
        
        # Add source info
        for p in pains:
            p["source"] = source
            p["extracted_at"] = datetime.now().isoformat()
        
        return pains
    except Exception as e:
        print(f"LLM extraction error for {source}: {e}")
        return []


def fetch_rss_pain_signals(limit_per_feed: int = 3) -> list[dict]:
    """Fetch pain signals from all RSS newsletters.
    
    Batches items into fewer LLM calls for speed.
    
    Args:
        limit_per_feed: Max items to fetch per newsletter
    
    Returns:
        List of pain signals extracted from newsletters
    """
    print("Fetching RSS newsletters...")
    items = fetch_all_newsletters(limit_per_feed=limit_per_feed)
    print(f"Fetched {len(items)} newsletter items")
    
    # Group by source for batch LLM extraction
    from collections import defaultdict
    by_source = defaultdict(list)
    for item in items:
        source = item.get("source", "unknown")
        title = item.get("title", "")
        description = item.get("description", "")
        text = f"{title}\n{description}"
        if len(text) >= 20:
            by_source[source].append(text)
    
    # Batch extract: one LLM call per source (max 3 texts per call)
    all_pains = []
    for source, texts in by_source.items():
        # Combine up to 3 texts into one LLM call
        batch = "\n---\n".join(texts[:3])
        pains = extract_pains_from_text(batch, source=source)
        all_pains.extend(pains)
    
    print(f"Extracted {len(all_pains)} pain signals from RSS ({len(by_source)} sources)")
    return all_pains


def fetch_historical_rss_pains(days: int = 60) -> list[dict]:
    """Fetch pain signals from newsletter archives via Exa search.
    
    Since RSS only keeps recent items, use Exa to search for historical
    content from newsletter archives.
    
    Args:
        days: How many days back to search
    
    Returns:
        List of pain signals from historical newsletter content
    """
    import os
    
    if not os.environ.get("EXA_API_KEY", ""):
        print("No EXA_API_KEY, skipping historical RSS pain search")
        return []
    
    newsletters = ["a16z", "Lenny's Newsletter", "Stratechery", "TLDR", 
                   "Not Boring", "The Generalist", "Dense Discovery", "Margins"]
    
    all_pains = []
    seen_urls = set()
    
    for newsletter in newsletters:
        # Search for pain-related content from this newsletter
        # Simple query with newsletter name + pain keywords
        queries = [
            f'{newsletter} frustration problem pain struggle',
            f'{newsletter} broken slow expensive need better alternative',
        ]
        
        for query in queries:
            try:
                resp = requests.post(
                    "https://api.exa.ai/search",
                    headers={
                        "x-api-key": os.environ.get("EXA_API_KEY", ""),
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "num_results": 3,
                        "type": "auto",
                        "contents": {"text": {"maxCharacters": 500}},
                        "startPublishedDate": (datetime.now() - __import__("datetime", fromlist=["datetime"]).timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z"),
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
                
                for r in data.get("results", [])[:3]:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        text = r.get("text", "") or ""
                        
                        # Extract pain signals from text
                        pains = extract_pains_from_text(text, source=newsletter)
                        for p in pains:
                            p["url"] = url
                            p["title"] = r.get("title", "")
                            p["published"] = r.get("publishedDate")
                        all_pains.extend(pains)
            except Exception as e:
                print(f"Historical RSS search error for {newsletter}: {e}")
    
    print(f"Extracted {len(all_pains)} pain signals from historical newsletters")
    return all_pains


if __name__ == "__main__":
    print("Testing RSS pain extraction...")
    pains = fetch_rss_pain_signals(limit_per_feed=3)
    for p in pains[:5]:
        print(f"  [{p.get('severity')}] {p.get('pain', '')[:80]}")
        print(f"    Source: {p.get('source')}, Category: {p.get('category')}")
        print()
