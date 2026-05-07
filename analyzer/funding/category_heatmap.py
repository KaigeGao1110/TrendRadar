"""Category Heatmap — aggregate funding data by category with heat scores."""

from datetime import datetime, timezone

from analyzer.funding.parser import parse_amount, parse_categories, load_funding_csv


def generate_heatmap(csv_path: str) -> dict:
    """Generate a category heatmap from funding CSV data.

    Heat score = company_count × 0.6 + funding_weight × 0.4 (normalized 0-100).

    Args:
        csv_path: Path to funding.csv.

    Returns:
        Dict with 'heatmap' list and 'generated_at' timestamp.
    """
    records = load_funding_csv(csv_path)

    # Aggregate per category
    cat_data: dict[str, dict] = {}  # category -> {count, total_funding_m}

    for rec in records:
        amount_m = rec["amount_m"]
        for cat in rec["categories"]:
            if cat not in cat_data:
                cat_data[cat] = {"count": 0, "total_funding_m": 0.0}
            cat_data[cat]["count"] += 1
            cat_data[cat]["total_funding_m"] += amount_m

    if not cat_data:
        return {"heatmap": [], "generated_at": datetime.now(timezone.utc).isoformat()}

    # Calculate heat scores
    max_count = max(d["count"] for d in cat_data.values())
    max_funding = max(d["total_funding_m"] for d in cat_data.values()) or 1.0

    heatmap = []
    for cat, data in cat_data.items():
        count_norm = data["count"] / max_count if max_count else 0
        funding_norm = data["total_funding_m"] / max_funding if max_funding else 0
        heat_score = round((count_norm * 0.6 + funding_norm * 0.4) * 100, 2)

        heatmap.append({
            "category": cat,
            "count": data["count"],
            "total_funding_m": round(data["total_funding_m"], 1),
            "heat_score": round(heat_score, 1),
        })

    # Sort by heat_score descending
    heatmap.sort(key=lambda x: x["heat_score"], reverse=True)

    return {
        "heatmap": heatmap,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }