"""Orchestrator for SEC Form D data ingestion.

Daily fetch from EDGAR API + quarterly bulk load from ZIP → Supabase.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

# Add project root to path when running directly
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.expanduser("~/.openclaw/.env"))
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"), override=True)
    except ImportError:
        pass

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None  # type: ignore
    Client = None  # type: ignore

from sources import sec_edgar, sec_edgar_bulk


def _get_supabase_client() -> Optional[Client]:
    """Initialize Supabase client from environment variables."""
    if not create_client:
        return None
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def _prepare_record_for_upsert(record: dict) -> dict:
    """Normalize a parsed record for Supabase upsert."""
    return {
        "accession_number": record.get("accession_number"),
        "entity_name": record.get("entity_name") or "Unknown",
        "cik": record.get("cik"),
        "filing_date": record.get("filing_date"),
        "date_of_first_sale": record.get("date_of_first_sale"),
        "total_offering_amount": record.get("total_offering_amount"),
        "total_amount_sold": record.get("total_amount_sold"),
        "total_remaining": record.get("total_remaining"),
        "industry_group": record.get("industry_group"),
        "sic_code": record.get("sic_code"),
        "entity_type": record.get("entity_type"),
        "jurisdiction": record.get("jurisdiction"),
        "city": record.get("city"),
        "state": record.get("state"),
        "investor_count": record.get("investor_count"),
        "source": record.get("source", "sec_edgar"),
    }


def ingest_daily(date_str: Optional[str] = None) -> dict:
    """Ingest Form D filings for a single day from EDGAR API.

    Args:
        date_str: Date string (YYYY-MM-DD). Defaults to yesterday.

    Returns:
        Summary dict with keys:
        - date: str
        - total_found: int
        - ingested: int
        - errors: int
        - top_deals: List[dict]
    """
    if date_str is None:
        date_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    client = _get_supabase_client()
    if not client:
        print("Supabase client not available. Check SUPABASE_URL and SUPABASE_KEY.")
        return {"date": date_str, "total_found": 0, "ingested": 0, "errors": 0, "top_deals": []}

    print(f"Fetching Form D filings for {date_str}...")
    try:
        filings = sec_edgar.fetch_form_d_filings_for_date(date_str)
    except Exception as e:
        print(f"Failed to fetch filings: {e}")
        return {"date": date_str, "total_found": 0, "ingested": 0, "errors": 1, "top_deals": []}

    ingested = 0
    errors = 0

    for filing in filings:
        record = _prepare_record_for_upsert(filing)
        record["source"] = "sec_edgar_api"
        try:
            client.table("sec_form_d_filings").upsert(
                record, on_conflict="accession_number"
            ).execute()
            ingested += 1
        except Exception as e:
            print(f"Upsert error for {record['accession_number']}: {e}")
            errors += 1

    # Top 10 deals by amount
    top_deals = sorted(
        [f for f in filings if f.get("total_offering_amount")],
        key=lambda x: x["total_offering_amount"] or 0,
        reverse=True,
    )[:10]

    summary = {
        "date": date_str,
        "total_found": len(filings),
        "ingested": ingested,
        "errors": errors,
        "top_deals": [
            {
                "entity_name": d.get("entity_name"),
                "amount": d.get("total_offering_amount"),
                "industry_group": d.get("industry_group"),
            }
            for d in top_deals
        ],
    }

    print(
        f"Daily ingest complete: {summary['ingested']} ingested, "
        f"{summary['errors']} errors"
    )
    return summary


def ingest_bulk(year: int, quarter: int) -> dict:
    """Ingest Form D filings from a quarterly ZIP bulk download.

    Args:
        year: Year (e.g. 2026).
        quarter: Quarter (1-4).

    Returns:
        Summary dict with keys:
        - year: int
        - quarter: int
        - downloaded: str (zip path)
        - parsed: int
        - ingested: int
        - errors: int
    """
    client = _get_supabase_client()
    if not client:
        print("Supabase client not available. Check SUPABASE_URL and SUPABASE_KEY.")
        return {"year": year, "quarter": quarter, "downloaded": "", "parsed": 0, "ingested": 0, "errors": 0}

    print(f"Downloading quarterly ZIP for {year} Q{quarter}...")
    try:
        zip_path = sec_edgar_bulk.download_quarterly_zip(year, quarter)
    except Exception as e:
        print(f"Download failed: {e}")
        return {"year": year, "quarter": quarter, "downloaded": "", "parsed": 0, "ingested": 0, "errors": 1}

    print(f"Parsing ZIP: {zip_path}...")
    try:
        records = sec_edgar_bulk.parse_quarterly_zip(zip_path)
    except Exception as e:
        print(f"Parse failed: {e}")
        return {"year": year, "quarter": quarter, "downloaded": zip_path, "parsed": 0, "ingested": 0, "errors": 1}

    ingested = 0
    errors = 0

    for record in records:
        prepared = _prepare_record_for_upsert(record)
        prepared["source"] = "sec_edgar_bulk"
        try:
            client.table("sec_form_d_filings").upsert(
                prepared, on_conflict="accession_number"
            ).execute()
            ingested += 1
        except Exception as e:
            print(f"Upsert error for {prepared['accession_number']}: {e}")
            errors += 1

    summary = {
        "year": year,
        "quarter": quarter,
        "downloaded": zip_path,
        "parsed": len(records),
        "ingested": ingested,
        "errors": errors,
    }

    print(
        f"Bulk ingest complete: {summary['parsed']} parsed, "
        f"{summary['ingested']} ingested, {summary['errors']} errors"
    )
    return summary


def generate_daily_report(date_str: Optional[str] = None) -> str:
    """Generate a markdown report for Form D filings on a given date.

    Args:
        date_str: Date string (YYYY-MM-DD). Defaults to yesterday.

    Returns:
        Path to the generated report file.
    """
    if date_str is None:
        date_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    client = _get_supabase_client()
    if not client:
        print("Supabase client not available. Report will be empty.")
        records: List[dict] = []
    else:
        try:
            result = (
                client.table("sec_form_d_filings")
                .select("*")
                .eq("filing_date", date_str)
                .execute()
            )
            records = result.data or []
        except Exception as e:
            print(f"Query error: {e}")
            records = []

    total = len(records)
    total_amount = sum(
        r.get("total_offering_amount") or 0 for r in records
    )

    # Industry breakdown
    industry_counts: Dict[str, int] = {}
    industry_amounts: Dict[str, float] = {}
    for r in records:
        ig = r.get("industry_group") or "Unknown"
        industry_counts[ig] = industry_counts.get(ig, 0) + 1
        industry_amounts[ig] = industry_amounts.get(ig, 0) + (r.get("total_offering_amount") or 0)

    sorted_industries = sorted(
        industry_counts.items(),
        key=lambda x: industry_amounts.get(x[0], 0),
        reverse=True,
    )

    # Top 10 deals
    top_deals = sorted(
        [r for r in records if r.get("total_offering_amount")],
        key=lambda x: x["total_offering_amount"] or 0,
        reverse=True,
    )[:10]

    lines = [
        f"# SEC Form D Daily Report — {date_str}",
        "",
        f"**Generated at:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"- **Total filings:** {total}",
        f"- **Total offering amount:** ${total_amount:,.0f}",
        "",
        "## Industry Breakdown",
        "",
        "| Industry | Count | Total Amount |",
        "|----------|-------|--------------|",
    ]

    for ig, count in sorted_industries[:15]:
        amt = industry_amounts.get(ig, 0)
        lines.append(f"| {ig} | {count} | ${amt:,.0f} |")

    lines.extend([
        "",
        "## Top 10 Deals by Amount",
        "",
        "| Company | Amount | Industry | State |",
        "|---------|--------|----------|-------|",
    ])

    for d in top_deals:
        lines.append(
            f"| {d.get('entity_name') or 'N/A'} | "
            f"${d.get('total_offering_amount') or 0:,.0f} | "
            f"{d.get('industry_group') or 'N/A'} | "
            f"{d.get('state') or 'N/A'} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "_Report generated by TrendRadar SEC Form D Ingestor_",
        "",
    ])

    output_dir = os.path.expanduser("~/Projects/TrendRadar/output")
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"sec_form_d_{date_str}.md")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report saved to {report_path}")
    return report_path


if __name__ == "__main__":
    # Quick test: ingest yesterday and generate report
    summary = ingest_daily()
    if summary["ingested"] > 0:
        generate_daily_report(summary["date"])
