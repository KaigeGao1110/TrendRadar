"""Big Rounds — filter and sort large funding rounds."""

from analyzer.funding.parser import load_funding_csv


def get_big_rounds(csv_path: str, threshold_m: float = 50.0) -> dict:
    """Get funding rounds at or above a threshold amount.

    Args:
        csv_path: Path to funding.csv.
        threshold_m: Minimum amount in millions (default 50).

    Returns:
        Dict with 'big_rounds' list, 'threshold_m', and 'total' count.
    """
    records = load_funding_csv(csv_path)
    big_rounds = []

    for rec in records:
        amount_m = rec["amount_m"]
        if amount_m < threshold_m:
            continue

        valuation_b = round(rec["valuation_m"] / 1000.0, 2) if rec["valuation_m"] > 0 else None

        big_rounds.append({
            "company": rec["company"],
            "amount_m": round(amount_m, 1),
            "valuation_b": valuation_b,
            "categories": rec["categories"],
            "url": rec["url"],
        })

    # Sort by amount descending
    big_rounds.sort(key=lambda x: x["amount_m"], reverse=True)

    return {
        "big_rounds": big_rounds,
        "threshold_m": threshold_m,
        "total": len(big_rounds),
    }
