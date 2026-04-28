"""SEC EDGAR quarterly ZIP bulk loader for Form D filings.

Downloads the quarterly structured data ZIP from SEC.gov, extracts TSV files,
and parses them into normalized records.
"""

import csv
import os
import sys
import tempfile
import zipfile
from typing import List, Dict, Optional

import requests

# Add project root to path when running directly
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QUARTERLY_ZIP_URL = (
    "https://www.sec.gov/files/structureddata/data/form-d-data-sets/{year}q{quarter}_d.zip"
)
EDGAR_USER_AGENT = "TrendRadar research@trendradar.ai"

INVESTMENT_FUND_KEYWORDS = [
    "Pooled Investment Fund",
    "Private Equity Fund",
    "Hedge Fund",
    "Venture Capital Fund",
    "Venture Capital",
]


def _get_headers() -> dict:
    """Return required SEC request headers."""
    return {"User-Agent": EDGAR_USER_AGENT}


def _is_investment_fund(entity_type: Optional[str], industry_group: Optional[str]) -> bool:
    """Return True if the filing appears to be an investment fund."""
    text = " ".join(filter(None, [entity_type, industry_group])).lower()
    return any(kw.lower() in text for kw in INVESTMENT_FUND_KEYWORDS)


def _safe_float(value: Optional[str], default: Optional[float] = None) -> Optional[float]:
    """Safely parse a float from string."""
    if not value:
        return default
    try:
        cleaned = value.replace(",", "").replace("$", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def _safe_int(value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    """Safely parse an int from string."""
    if not value:
        return default
    try:
        return int(value.replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def download_quarterly_zip(year: int, quarter: int) -> str:
    """Download the quarterly Form D ZIP file from SEC.gov.

    Args:
        year: Year (e.g. 2026).
        quarter: Quarter (1-4).

    Returns:
        Path to the downloaded ZIP file.
    """
    url = QUARTERLY_ZIP_URL.format(year=year, quarter=quarter)
    zip_path = f"/tmp/formd_{year}q{quarter}.zip"

    resp = requests.get(url, headers=_get_headers(), timeout=120)
    resp.raise_for_status()

    with open(zip_path, "wb") as f:
        f.write(resp.content)

    return zip_path


def parse_quarterly_zip(zip_path: str) -> List[dict]:
    """Parse a quarterly Form D ZIP into normalized records.

    Extracts ISSUERS.tsv and OFFERING.tsv, joins on ACCESSIONNUMBER,
    filters out investment funds and offerings under $1M.

    Args:
        zip_path: Path to the downloaded ZIP file.

    Returns:
        List of dicts with keys:
        - accession_number
        - entity_name
        - cik
        - filing_date
        - date_of_first_sale
        - total_offering_amount
        - industry_group
        - entity_type
        - city
        - state
        - investor_count
    """
    records: List[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)

        # Find TSV files (case-insensitive, may be nested)
        issuers_path: Optional[str] = None
        offering_path: Optional[str] = None

        for root, _dirs, files in os.walk(tmpdir):
            for fname in files:
                lower = fname.lower()
                if lower == "issuers.tsv":
                    issuers_path = os.path.join(root, fname)
                elif lower == "offering.tsv":
                    offering_path = os.path.join(root, fname)

        if not issuers_path or not offering_path:
            raise FileNotFoundError(
                f"ISSUERS.tsv or OFFERING.tsv not found in {zip_path}"
            )

        # Find FORMDSUBMISSION.tsv
        submission_path: Optional[str] = None
        for root, _dirs, files in os.walk(tmpdir):
            for fname in files:
                if fname.lower() == "formdsubmission.tsv":
                    submission_path = os.path.join(root, fname)
                    break

        # Load issuers
        issuers: Dict[str, dict] = {}
        with open(issuers_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                acc = row.get("ACCESSIONNUMBER", "").strip()
                if not acc:
                    continue
                issuers[acc] = {
                    "entity_name": row.get("ENTITYNAME", "").strip() or None,
                    "cik": row.get("CIK", "").strip() or None,
                    "entity_type": row.get("ENTITYTYPE", "").strip() or None,
                    "city": row.get("CITY", "").strip() or None,
                    "state": row.get("STATEORCOUNTRY", "").strip() or None,
                }

        # Load submission metadata (for filing_date and sic_code)
        submissions = {}
        if submission_path and os.path.exists(submission_path):
            with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    acc = row.get("ACCESSIONNUMBER", "").strip()
                    if acc:
                        submissions[acc] = {
                            "filing_date": row.get("FILING_DATE", "").strip() or None,
                            "sic_code": row.get("SIC_CODE", "").strip() or None,
                        }

        # Load offering and join
        with open(offering_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                acc = row.get("ACCESSIONNUMBER", "").strip()
                if not acc or acc not in issuers:
                    continue

                issuer = issuers[acc]
                industry_group = row.get("INDUSTRYGROUPTYPE", "").strip() or None
                entity_type = issuer.get("entity_type")

                # Skip investment funds
                if _is_investment_fund(entity_type, industry_group):
                    continue

                # Skip offerings under $1M
                amount = _safe_float(row.get("TOTALOFFERINGAMOUNT"))
                if amount is not None and amount < 1_000_000:
                    continue

                sub = submissions.get(acc, {})
                record = {
                    "accession_number": acc,
                    "entity_name": issuer.get("entity_name"),
                    "cik": issuer.get("cik"),
                    "filing_date": sub.get("filing_date"),
                    "date_of_first_sale": row.get("SALE_DATE", row.get("DATEOFFIRSTSALE", "")).strip() or None,
                    "total_offering_amount": amount,
                    "industry_group": industry_group,
                    "sic_code": sub.get("sic_code"),
                    "entity_type": entity_type,
                    "city": issuer.get("city"),
                    "state": issuer.get("state"),
                    "investor_count": _safe_int(row.get("TOTALNUMBERALREADYINVESTED")),
                }
                records.append(record)

    return records


if __name__ == "__main__":
    # Quick test: download and parse 2026 Q1
    print("Testing SEC EDGAR bulk download for 2026 Q1...")
    try:
        zip_path = download_quarterly_zip(2026, 1)
        print(f"Downloaded to {zip_path}")
        records = parse_quarterly_zip(zip_path)
        print(f"Parsed {len(records)} records")
        for r in records[:5]:
            print(
                f"  {r['entity_name'] or 'N/A'} | "
                f"${r['total_offering_amount'] or 0:,.0f} | "
                f"{r['industry_group'] or 'N/A'}"
            )
    except Exception as e:
        print(f"Bulk test failed: {e}")
