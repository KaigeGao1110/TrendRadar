#!/usr/bin/env python3
"""Fetch 2 months of historical pain signals from Exa + RSS."""

import os
import sys
import json
import time
from datetime import datetime

# Load env
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.openclaw/.env"))
load_dotenv(".env", override=True)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources.exa_pain import search_historical_pains, fetch_all_pain_signals
from sources.rss_pain import fetch_historical_rss_pains, fetch_rss_pain_signals


def main():
    print("=" * 60)
    print("Historical Pain Signal Fetch — 2 Months")
    print("=" * 60)
    
    all_signals = []
    
    # 1. Exa semantic search (2 months)
    print("\n[1/3] Exa: semantic pain search (2 months)...")
    exa_signals = search_historical_pains(days=60, limit_per_query=3)
    print(f"  Found {len(exa_signals)} signals from Exa")
    all_signals.extend(exa_signals)
    
    # 2. RSS newsletter pain extraction (2 months)
    print("\n[2/3] RSS: historical newsletter pain extraction (2 months)...")
    rss_signals = fetch_historical_rss_pains(days=60)
    print(f"  Found {len(rss_signals)} signals from RSS")
    all_signals.extend(rss_signals)
    
    # 3. Current pain signals (for context)
    print("\n[3/3] Current pain signals (for context)...")
    current_exa = fetch_all_pain_signals(queries=["what do professionals struggle with"], limit_per_query=2)
    print(f"  Found {len(current_exa)} current signals from Exa")
    all_signals.extend(current_exa)
    
    # Deduplicate
    seen_urls = set()
    unique_signals = []
    for s in all_signals:
        url = s.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_signals.append(s)
    
    print(f"\n{'=' * 60}")
    print(f"Total unique signals: {len(unique_signals)}")
    print(f"  Exa (2 months): {len(exa_signals)}")
    print(f"  RSS (2 months): {len(rss_signals)}")
    print(f"  Current Exa: {len(current_exa)}")
    
    # Save to file
    output_dir = os.path.expanduser("~/Projects/TrendRadar/output")
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, "historical_pains.json")
    with open(output_file, "w") as f:
        json.dump(unique_signals, f, indent=2, default=str)
    
    print(f"\nSaved to {output_file}")
    
    # Display top signals
    print(f"\n{'=' * 60}")
    print("Top Pain Signals:")
    print("=" * 60)
    for i, s in enumerate(unique_signals[:20], 1):
        title = s.get("title", "")[:60]
        source = s.get("source", "unknown")
        newsletter = s.get("newsletter", "")
        snippet = s.get("snippet", "")[:80]
        print(f"\n{i}. [{source}] {title}")
        if newsletter:
            print(f"   Newsletter: {newsletter}")
        print(f"   {snippet}...")


if __name__ == "__main__":
    main()
