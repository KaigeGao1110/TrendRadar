"""Pricing Anchor — aggregate valuation statistics by category."""

import statistics
from collections import defaultdict
from datetime import datetime, timezone

from analyzer.funding.parser import load_funding_csv


def calculate_pricing_anchors(csv_path: str) -> dict:
    """Calculate valuation statistics per category.

    Computes min, max, avg, median, p25, p75 for each category.

    Args:
        csv_path: Path to funding.csv.

    Returns:
        Dict with 'anchors' keyed by category, containing valuation stats.
    """
    records = load_funding_csv(csv_path)

    # Collect valuations per category
    cat_valuations: dict[str, list[float]] = defaultdict(list)

    for rec in records:
        valuation_m = rec["valuation_m"]
        if valuation_m <= 0:
            continue

        for cat in rec["categories"]:
            cat_valuations[cat].append(valuation_m)

    anchors = {}
    for cat, vals in cat_valuations.items():
        if not vals:
            continue

        sorted_vals = sorted(vals)
        count = len(sorted_vals)
        avg = sum(sorted_vals) / count
        median = statistics.median(sorted_vals)

        # Percentiles
        def percentile(data: list[float], p: float) -> float:
            """Calculate the p-th percentile (0-100)."""
            if not data:
                return 0.0
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = f + 1 if f + 1 < len(data) else f
            return data[f] + (k - f) * (data[c] - data[f])

        p25 = percentile(sorted_vals, 25)
        p75 = percentile(sorted_vals, 75)

        anchors[cat] = {
            "count": count,
            "min_m": round(min(sorted_vals), 1),
            "max_m": round(max(sorted_vals), 1),
            "avg_m": round(avg, 1),
            "median_m": round(median, 1),
            "p25_m": round(p25, 1),
            "p75_m": round(p75, 1),
        }

    # Sort by count descending
    sorted_anchors = dict(sorted(anchors.items(), key=lambda x: x[1]["count"], reverse=True))

    return {
        "anchors": sorted_anchors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }