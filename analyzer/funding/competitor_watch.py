"""Competitor Watch — track funding by category keywords."""

from analyzer.funding.parser import load_funding_csv


def watch_competitors(csv_path: str, keywords: list[str]) -> dict:
    """Find funding events matching category keywords.

    Case-insensitive keyword matching against category field.

    Args:
        csv_path: Path to funding.csv.
        keywords: List of keywords to match (e.g., ["AI", "SaaS"]).

    Returns:
        Dict with 'matches' list, 'keywords', and 'total_matches' count.
    """
    if not keywords:
        return {
            "matches": [],
            "keywords": [],
            "total_matches": 0,
        }

    # Normalize keywords for case-insensitive matching
    keywords_lower = [kw.lower() for kw in keywords]
    records = load_funding_csv(csv_path)
    matches = []

    for rec in records:
        categories_lower = [cat.lower() for cat in rec["categories"]]

        # Check if any keyword matches any category (case-insensitive substring)
        matched = False
        for kw_lower in keywords_lower:
            for cat_lower in categories_lower:
                if kw_lower in cat_lower or cat_lower in kw_lower:
                    matched = True
                    break
            if matched:
                break

        if not matched:
            continue

        matches.append({
            "company": rec["company"],
            "amount_m": round(rec["amount_m"], 1) if rec["amount_m"] > 0 else None,
            "categories": rec["categories"],
            "url": rec["url"],
        })

    # Sort by amount descending (None/0 values at end)
    matches.sort(key=lambda x: x["amount_m"] or 0, reverse=True)

    return {
        "matches": matches,
        "keywords": keywords,
        "total_matches": len(matches),
    }