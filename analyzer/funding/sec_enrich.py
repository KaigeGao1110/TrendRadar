"""Orchestrator for SEC company enrichment.

Fetches unenriched companies from sec_form_d_filings,
enriches them via web search + LLM, and stores in sec_company_profiles.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional, Set

# Add project root to path when running directly
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.expanduser("~/.openclaw/.env"))
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"), override=True)
    except ImportError:
        pass

from storage.sec_local_db import SecLocalDB
from sources import sec_enrichment


# Industries to skip (irrelevant for TrendRadar)
SKIP_INDUSTRIES = {
    "Commercial",
    "Other Real Estate",
    "Residential",
    "REITS and Finance",
    "Insurance",
    "Other Banking and Financial Services",
    "Oil and Gas",
    "Coal Mining",
    "Lodging and Conventions",
    "Agriculture",
    "Environmental Services",
    "Restaurants",
    "Retailing",
    "Investment Banking",
    "Tourism and Travel Services",
    "Other Travel",
}


def get_unenriched_companies(limit: Optional[int] = None) -> List[dict]:
    """Query sec_form_d_filings for records not yet enriched.

    Filters out irrelevant industries and deduplicates by normalized_name.

    Args:
        limit: Maximum number of unique companies to return.

    Returns:
        List of dicts with keys:
        - entity_name: original company name
        - accession_numbers: list of related accession numbers
        - industry_group: industry classification
        - total_offering_amount: funding amount
    """
    db = SecLocalDB()
    existing_names = db.get_existing_normalized_names()

    all_filings = db.get_all_filings()
    print(f"Fetched {len(all_filings)} total filings")

    # Filter: skip irrelevant industries and already-enriched companies
    companies: Dict[str, dict] = {}
    for filing in all_filings:
        industry = filing.get("industry_group") or ""
        if industry in SKIP_INDUSTRIES:
            continue

        entity_name = filing.get("entity_name") or ""
        if not entity_name:
            continue

        normalized = sec_enrichment.normalize_name(entity_name)
        if normalized in existing_names:
            continue

        if normalized not in companies:
            companies[normalized] = {
                "entity_name": entity_name,
                "accession_numbers": [],
                "industry_group": industry,
                "total_offering_amount": filing.get("total_offering_amount"),
            }

        acc = filing.get("accession_number")
        if acc and acc not in companies[normalized]["accession_numbers"]:
            companies[normalized]["accession_numbers"].append(acc)

    # Convert to list, sorted by total_offering_amount desc
    results = sorted(
        companies.values(),
        key=lambda x: x.get("total_offering_amount") or 0,
        reverse=True,
    )

    if limit:
        results = results[:limit]

    return results


def enrich_and_store(company: dict) -> bool:
    """Enrich a single company and upsert into sec_company_profiles.

    Args:
        company: Dict with entity_name, accession_numbers, etc.

    Returns:
        True if successful, False otherwise.
    """
    db = SecLocalDB()

    entity_name = company.get("entity_name", "")
    if not entity_name:
        print("Empty entity_name, skipping")
        return False

    try:
        enriched = sec_enrichment.enrich_company(entity_name)
    except Exception as e:
        print(f"Enrichment error for '{entity_name}': {e}")
        return False

    # Skip if we got almost nothing back
    if enriched.get("enrichment_quality") == "low" and not enriched.get("description"):
        print(f"Low quality enrichment for '{entity_name}', storing anyway")

    record = {
        "normalized_name": enriched["normalized_name"],
        "entity_name": enriched["entity_name"],
        "description": enriched.get("description"),
        "sector": enriched.get("sector"),
        "main_business": enriched.get("main_business"),
        "website": enriched.get("website"),
        "accession_numbers": company.get("accession_numbers", []),
        "enrichment_source": enriched.get("enrichment_source"),
        "enrichment_quality": enriched.get("enrichment_quality"),
        "enriched_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        db.upsert_profile(record)
        return True
    except Exception as e:
        print(f"Upsert error for '{entity_name}': {e}")
        return False


def run_bulk_enrichment(limit: Optional[int] = None) -> dict:
    """Run bulk enrichment for all unenriched companies.

    Args:
        limit: Maximum number of companies to process.

    Returns:
        Summary dict with keys:
        - total: total companies attempted
        - enriched: successfully enriched and stored
        - errors: failed enrichments
        - sectors_found: dict of sector -> count
    """
    db = SecLocalDB()
    companies = get_unenriched_companies(limit=limit)
    total = len(companies)
    enriched = 0
    errors = 0

    print(f"Starting bulk enrichment for {total} companies...")

    for i, company in enumerate(companies, start=1):
        name = company.get("entity_name", "Unknown")
        print(f"[{i}/{total}] Enriching: {name}")

        success = enrich_and_store(company)
        if success:
            enriched += 1
        else:
            errors += 1

        if i % 50 == 0:
            print(f"Progress: {i}/{total} processed ({enriched} enriched, {errors} errors)")

        # Rate limit: 1 second between companies
        if i < total:
            time.sleep(1)

    # Get sector counts from the database
    sectors_found = db.get_sector_counts()

    summary = {
        "total": total,
        "enriched": enriched,
        "errors": errors,
        "sectors_found": sectors_found,
    }

    print(
        f"Bulk enrichment complete: {summary['enriched']}/{summary['total']} enriched, "
        f"{summary['errors']} errors"
    )
    if sectors_found:
        print("Sectors found:")
        for sector, count in sorted(sectors_found.items(), key=lambda x: x[1], reverse=True):
            print(f"  {sector}: {count}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SEC company enrichment runner")
    parser.add_argument("--limit", type=int, default=None, help="Max companies to enrich")
    args = parser.parse_args()

    run_bulk_enrichment(limit=args.limit)
