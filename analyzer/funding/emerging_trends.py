"""Emerging Trends — detect categories growing in frequency over time."""

from datetime import datetime, timezone, timedelta
from collections import defaultdict

from analyzer.funding.parser import load_funding_csv


def detect_emerging(
    csv_path: str,
    this_week_days: int = 7,
    baseline_days: int = 30,
) -> dict:
    """Detect emerging categories based on frequency growth.

    Compares category frequency in the recent week vs a 30-day baseline.

    Args:
        csv_path: Path to funding.csv.
        this_week_days: Days for "this week" window (default 7).
        baseline_days: Days for baseline window (default 30).

    Returns:
        Dict with 'emerging' list sorted by growth_rate descending.
    """
    records = load_funding_csv(csv_path)
    now = datetime.now(timezone.utc)
    this_week_start = now - timedelta(days=this_week_days)
    baseline_start = now - timedelta(days=baseline_days)

    # Count categories in each window
    this_week: dict[str, int] = defaultdict(int)
    baseline: dict[str, int] = defaultdict(int)

    for rec in records:
        first_seen = rec.get("first_seen_at_dt")
        if not first_seen:
            continue

        for cat in rec["categories"]:
            if first_seen >= this_week_start:
                this_week[cat] += 1
            if baseline_start <= first_seen < this_week_start:
                baseline[cat] += 1

    # Calculate growth rates
    # baseline_avg = baseline count / (baseline_days / this_week_days)
    # This normalizes baseline to the same time window as "this week"
    baseline_avg_divisor = baseline_days / this_week_days

    emerging = []
    for cat, this_week_count in this_week.items():
        baseline_count = baseline.get(cat, 0)
        baseline_avg = baseline_count / baseline_avg_divisor if baseline_count else 0

        # Calculate growth rate
        # Avoid division by zero — if baseline is 0, use a minimum of 1 for growth calculation
        if baseline_avg == 0:
            growth_rate = float(this_week_count) if this_week_count > 0 else 0.0
        else:
            growth_rate = this_week_count / baseline_avg

        emerging.append({
            "category": cat,
            "this_week": this_week_count,
            "baseline_avg": round(baseline_avg, 1),
            "baseline_total": baseline_count,
            "growth_rate": round(growth_rate, 2),
        })

    # Sort by growth_rate descending
    emerging.sort(key=lambda x: x["growth_rate"], reverse=True)

    return {
        "emerging": emerging,
        "this_week_window_days": this_week_days,
        "baseline_window_days": baseline_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }