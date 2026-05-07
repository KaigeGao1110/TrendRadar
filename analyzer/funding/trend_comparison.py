"""Trend Comparison — compare category heat between two time periods."""

from typing import Optional


def compare_trends(
    current_heatmap: dict,
    previous_heatmap: dict,
    change_threshold: float = 10.0,
) -> dict:
    """Compare two heatmap snapshots and classify category trends.

    Args:
        current_heatmap: Heatmap dict from category_heatmap (current period).
        previous_heatmap: Heatmap dict from category_heatmap (previous period).
        change_threshold: Minimum % change to classify as warming/cooling (default 10%).

    Returns:
        Dict with 'warming', 'cooling', 'stable' lists.
    """
    # Build lookup dicts: category -> heat_score
    current_scores = {
        item["category"]: item["heat_score"]
        for item in current_heatmap.get("heatmap", [])
    }
    previous_scores = {
        item["category"]: item["heat_score"]
        for item in previous_heatmap.get("heatmap", [])
    }

    # All categories across both periods
    all_categories = set(current_scores.keys()) | set(previous_scores.keys())

    warming = []
    cooling = []
    stable = []

    for cat in all_categories:
        curr = current_scores.get(cat, 0.0)
        prev = previous_scores.get(cat, 0.0)

        # Calculate percentage change
        if prev == 0:
            if curr > 0:
                change_pct = 100.0  # New category
            else:
                change_pct = 0.0
        else:
            change_pct = ((curr - prev) / prev) * 100.0

        entry = {
            "category": cat,
            "current_score": round(curr, 1),
            "previous_score": round(prev, 1),
            "change_pct": round(change_pct, 1),
        }

        if change_pct > change_threshold:
            warming.append(entry)
        elif change_pct < -change_threshold:
            cooling.append(entry)
        else:
            stable.append(entry)

    # Sort by magnitude
    warming.sort(key=lambda x: x["change_pct"], reverse=True)
    cooling.sort(key=lambda x: x["change_pct"])
    stable.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

    return {
        "warming": warming,
        "cooling": cooling,
        "stable": stable,
    }