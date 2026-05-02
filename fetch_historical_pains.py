#!/usr/bin/env python3
"""Fetch 2 months of historical pain signals — Exa only (fast)."""

import os, sys, json
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.openclaw/.env"))
load_dotenv(".env", override=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources.exa_pain import search_historical_pains

def main():
    print("=" * 60)
    print("Historical Pain Signal Fetch — 2 Months (Exa)")
    print("=" * 60)

    newsletters = [
        "a16z", "Lenny's Newsletter", "Stratechery", "TLDR",
        "Not Boring", "The Generalist", "Dense Discovery", "Margins",
    ]

    # Exa historical search
    print("\n[1/1] Exa semantic pain search (60 days)...")
    signals = search_historical_pains(newsletter_ids=newsletters, days=60, limit_per_query=3)
    print(f"Found {len(signals)} signals")

    # Save
    output_dir = os.path.expanduser("~/Projects/TrendRadar/output")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "historical_pains.json")
    with open(output_file, "w") as f:
        json.dump(signals, f, indent=2, default=str)
    print(f"Saved to {output_file}")

    # Summary by newsletter
    by_nl = {}
    for s in signals:
        nl = s.get("newsletter", "unknown")
        by_nl[nl] = by_nl.get(nl, 0) + 1

    print(f"\n{'=' * 60}")
    print("Summary by newsletter:")
    for nl, count in sorted(by_nl.items(), key=lambda x: -x[1]):
        print(f"  {nl}: {count}")

    # Top signals
    print(f"\nTop signals:")
    for i, s in enumerate(signals[:15], 1):
        print(f"  {i}. [{s.get('newsletter','')}] {s.get('title','')[:70]}")

if __name__ == "__main__":
    main()
