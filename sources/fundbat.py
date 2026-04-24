#!/usr/bin/env python3
"""FundBat - free startup funding data source
Scrapes https://fundbat.com - 791 companies, weekly updates
No API available, uses Playwright to scrape CSR pages
"""

import time
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page, Browser

# Output structure matches existing trend data format
FUNDBAT_URL = "https://fundbat.com/companies"

def fetch_all_companies(limit: Optional[int] = None) -> List[Dict]:
    """Fetch all listed companies from FundBat
    Args:
        limit: max companies to fetch (None = all 791)
    Returns:
        List of company dicts with fields:
        - name: company name
        - funding_amount: total funding amount (e.g. "$1.2B")
        - valuation: company valuation (e.g. "$840B")
        - category: industry/sector
        - location: country/region
        - founded_year: year founded
        - status: Private/Public
        - url: company page on FundBat
        - source: "fundbat"
        - crawled_at: ISO timestamp
    """
    companies = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
            )
            page: Page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
            
            # Navigate to companies page
            page.goto(FUNDBAT_URL, timeout=30000)
            time.sleep(2)  # Wait for initial render

            # Scroll to load all companies (table pagination)
            scroll_pause = 1.5
            last_row_count = 0
            
            while True:
                # Scroll to bottom
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(scroll_pause)
                
                # Check if new rows loaded
                rows = page.locator("tr.table-row").all()
                current_row_count = len(rows)
                
                if current_row_count == last_row_count:
                    break  # No more rows
                last_row_count = current_row_count
                
                if limit and current_row_count >= limit:
                    break

            # Extract data from table rows
            rows = page.locator("tr.table-row").all()
            print(f"Total rows found: {len(rows)}")
            
            for i, row in enumerate(rows):
                try:
                    tds = row.locator("td").all()
                    if len(tds) < 8:
                        continue  # Skip bad rows
                    
                    # Column 1: Company name + link
                    name = tds[1].text_content().strip()
                    if not name:
                        continue
                    
                    # Get URL
                    url = tds[1].locator("a").first.get_attribute("href")
                    if url and not url.startswith("http"):
                        url = f"https://fundbat.com{url}"
                    
                    # Column 2: Category
                    category = tds[2].text_content().strip()
                    
                    # Column 3: Location
                    location = tds[3].text_content().strip()
                    
                    # Column 4: Founded year
                    founded_year = tds[4].text_content().strip()
                    
                    # Column 5: Status (Private/Public)
                    status = tds[5].text_content().strip()
                    
                    # Column 6: Valuation
                    valuation = tds[6].text_content().strip()
                    
                    # Column 7: Total funding
                    funding_amount = tds[7].text_content().strip()

                    companies.append({
                        "name": name,
                        "funding_amount": funding_amount,
                        "valuation": valuation,
                        "category": category,
                        "location": location,
                        "founded_year": founded_year,
                        "status": status,
                        "url": url,
                        "source": "fundbat",
                        "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    })

                    if limit and len(companies) >= limit:
                        break

                except Exception as e:
                    continue  # Skip bad rows

            return companies

    except Exception as e:
        print(f"FundBat scrape error: {e}")
        return []


def fetch_recent_companies(days: int = 7) -> List[Dict]:
    """Fetch companies added in the past X days (FundBat updates weekly)"""
    # FundBat doesn't expose dates - return all and filter later
    return fetch_all_companies()


if __name__ == "__main__":
    # Test run
    print("Testing FundBat scraper...")
    companies = fetch_all_companies(limit=10)
    print(f"Fetched {len(companies)} companies")
    for i, company in enumerate(companies[:5]):
        print(f"{i+1}. {company['name']:30} | {company['funding_amount']:10} | {company['valuation']:12} | {company['category'][:20]} | {company['location']}")
