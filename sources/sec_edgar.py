"""SEC EDGAR API client for Form D filings.

Provides real-time access to Form D (Notice of Exempt Offering) filings via:
- EDGAR Full-Text Search API: search by date range
- Individual XML fetch: parse offering details

SEC requires a custom User-Agent header for all requests.
"""

import os
import sys
import time
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

import requests

# Add project root to path when running directly
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_XML_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/primary_doc.xml"
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


def search_form_d_filings(
    start_date: str,
    end_date: str,
    size: int = 100,
    offset: int = 0,
) -> dict:
    """Search EDGAR for Form D filings within a date range.

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        size: Number of results per page (max 100).
        offset: Pagination offset.

    Returns:
        Raw JSON response from EDGAR search API.
    """
    params = {
        "forms": "D",
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "hits.hits.total": "true",
        "size": size,
        "from": offset,
    }
    resp = requests.get(
        EDGAR_SEARCH_URL,
        params=params,
        headers=_get_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _strip_accession_dashes(acc: str) -> str:
    """Remove dashes from accession number for URL construction."""
    return acc.replace("-", "")


def _is_investment_fund(entity_type: Optional[str], industry_group: Optional[str]) -> bool:
    """Return True if the filing appears to be an investment fund."""
    text = " ".join(filter(None, [entity_type, industry_group])).lower()
    return any(kw.lower() in text for kw in INVESTMENT_FUND_KEYWORDS)


def _safe_get_text(element: Optional[ET.Element], default: Optional[str] = None) -> Optional[str]:
    """Safely extract text from an XML element."""
    if element is None:
        return default
    return element.text.strip() if element.text else default


def _safe_get_float(element: Optional[ET.Element], default: Optional[float] = None) -> Optional[float]:
    """Safely extract float value from an XML element."""
    text = _safe_get_text(element)
    if text is None:
        return default
    try:
        # Remove commas and dollar signs
        cleaned = text.replace(",", "").replace("$", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def fetch_form_d_xml(cik: str, accession_number: str) -> dict:
    """Fetch and parse Form D primary_doc.xml from EDGAR.

    Args:
        cik: Company CIK (10 digits, zero-padded).
        accession_number: EDGAR accession number (e.g. '0001234567-26-000123').

    Returns:
        Dict with extracted fields:
        - entity_name
        - date_of_first_sale
        - total_offering_amount
        - total_amount_sold
        - total_remaining
        - industry_group
        - investor_count
        - entity_type
        - jurisdiction
        - city
        - state
        - sic_code
    """
    url = EDGAR_XML_URL.format(
        cik=cik.lstrip("0") or "0",
        accession_no_dashes=_strip_accession_dashes(accession_number),
    )
    resp = requests.get(url, headers=_get_headers(), timeout=30)
    resp.raise_for_status()

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise ValueError(f"XML parse error for {accession_number}: {e}") from e

    # Simple tag-based search (ignores namespaces)
    def findtext(tag: str) -> Optional[str]:
        """Find first element by tag name (ignoring namespace) and return text."""
        for elem in root.iter():
            local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local == tag:
                text = (elem.text or "").strip()
                if text:
                    return text
        return None

    def findtext_in(parent_tag: str, child_tag: str) -> Optional[str]:
        """Find text of child_tag inside first parent_tag element."""
        for elem in root.iter():
            local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local == parent_tag:
                for child in elem:
                    child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if child_local == child_tag:
                        return (child.text or "").strip() or None
        return None

    def findfloat(tag: str) -> Optional[float]:
        text = findtext(tag)
        if text:
            try:
                return float(text)
            except (ValueError, TypeError):
                pass
        return None

    def findint(tag: str) -> Optional[int]:
        text = findtext(tag)
        if text:
            try:
                return int(text)
            except (ValueError, TypeError):
                pass
        return None

    # Entity info
    entity_name = findtext("entityName")
    entity_type = findtext("entityType")
    jurisdiction = findtext("jurisdictionOfInc")
    city = findtext("city")
    state = findtext("stateOrCountry")
    sic_code = findtext("sicCode")

    # Offering info
    industry_group = findtext("industryGroupType")
    date_of_first_sale = findtext_in("dateOfFirstSale", "value")

    # Amounts
    total_offering_amount = findfloat("totalOfferingAmount")
    total_amount_sold = findfloat("totalAmountSold")
    total_remaining = findfloat("totalRemaining")

    # Investor count
    investor_count = findint("totalNumberAlreadyInvested")

    return {
        "entity_name": entity_name,
        "date_of_first_sale": date_of_first_sale,
        "total_offering_amount": total_offering_amount,
        "total_amount_sold": total_amount_sold,
        "total_remaining": total_remaining,
        "industry_group": industry_group,
        "investor_count": investor_count,
        "entity_type": entity_type,
        "jurisdiction": jurisdiction,
        "city": city,
        "state": state,
        "sic_code": sic_code,
    }


def fetch_form_d_filings_for_date(date_str: str) -> List[dict]:
    """Fetch all Form D filings for a single date, excluding investment funds.

    Args:
        date_str: Date string (YYYY-MM-DD).

    Returns:
        List of parsed filing dicts with keys:
        - accession_number
        - cik
        - filing_date
        - entity_name
        - date_of_first_sale
        - total_offering_amount
        - total_amount_sold
        - total_remaining
        - industry_group
        - investor_count
        - entity_type
        - jurisdiction
        - city
        - state
        - sic_code
    """
    results: List[dict] = []
    offset = 0
    size = 100

    while True:
        try:
            data = search_form_d_filings(date_str, date_str, size=size, offset=offset)
        except requests.RequestException as e:
            print(f"EDGAR search error for {date_str}: {e}")
            break

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})
            accession_number = source.get("adsh")
            cik_list = source.get("ciks", [])
            cik = cik_list[0] if cik_list else None
            filing_date = source.get("file_date")

            if not accession_number or not cik:
                continue

            # Fetch XML with rate limiting (SEC limit: 10 req/sec)
            time.sleep(0.5)

            try:
                parsed = fetch_form_d_xml(cik, accession_number)
            except (requests.RequestException, ValueError) as e:
                print(f"Error fetching XML for {accession_number}: {e}")
                continue

            # Skip investment funds
            if _is_investment_fund(parsed.get("entity_type"), parsed.get("industry_group")):
                continue

            record = {
                "accession_number": accession_number,
                "cik": cik,
                "filing_date": filing_date,
                **parsed,
            }
            results.append(record)

        if len(hits) < size:
            break
        offset += size

    return results


if __name__ == "__main__":
    # Quick test: fetch yesterday's filings
    from datetime import datetime, timedelta

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Testing SEC EDGAR fetch for {yesterday}...")
    filings = fetch_form_d_filings_for_date(yesterday)
    print(f"Found {len(filings)} non-fund filings")
    for f in filings[:5]:
        print(
            f"  {f['entity_name'] or 'N/A'} | "
            f"${f['total_offering_amount'] or 0:,.0f} | "
            f"{f['industry_group'] or 'N/A'}"
        )
