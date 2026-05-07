"""Anomaly Detection — detect categories with unusual funding activity."""

import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from analyzer.funding.parser import load_funding_csv


def detect_anomalies(
    csv_path: str,
    this_week_days: int = 7,
    baseline_days: int = 30,
    sigma_threshold: float = 2.0,
) -> dict:
    """Detect categories with anomalous funding activity.

    Computes per-category baseline frequency, then checks if the current
    week deviates more than sigma_threshold standard deviations.

    Args:
        csv_path: Path to funding.csv.
        this_week_days: Days for current window (default 7).
        baseline_days: Days for baseline window (default 30).
        sigma_threshold: Standard deviation threshold (default 2.0).

    Returns:
        Dict with 'anomalies' list sorted by deviation descending.
    """
    records = load_funding_csv(csv_path)
    now = datetime.now(timezone.utc)
    this_week_start = now - timedelta(days=this_week_days)
    baseline_start = now - timedelta(days=baseline_days)
    baseline_length = baseline_days - this_week_days
    if baseline_length <= 0:
        baseline_length = 1  # avoid division by zero / empty lists

    # Collect daily per-category counts for baseline
    daily_counts: dict[str, list[int]] = defaultdict(lambda: [0] * baseline_length)
    this_week_counts: dict[str, int] = defaultdict(int)

    for rec in records:
        first_seen = rec.get("first_seen_at_dt")
        if not first_seen:
            continue

        for cat in rec["categories"]:
            if first_seen >= this_week_start:
                this_week_counts[cat] += 1

            if first_seen >= baseline_start and first_seen < this_week_start:
                day_index = (now - first_seen).days - this_week_days
                if 0 <= day_index < baseline_length:
                    daily_counts[cat][day_index] += 1

    anomalies = []
    for cat, this_week_count in this_week_counts.items():
        counts = daily_counts[cat]

        # Need at least a few data points for meaningful stats
        total_baseline = sum(counts)
        if total_baseline < 3:
            continue

        baseline_avg = total_baseline / baseline_length
        # Weekly baseline expectation
        weekly_baseline_avg = baseline_avg * this_week_days

        if weekly_baseline_avg == 0:
            continue

        # Standard deviation of daily counts
        if len(counts) > 1:
            variance = sum((c - baseline_avg) ** 2 for c in counts) / len(counts)
            std_dev = math.sqrt(variance) * math.sqrt(this_week_days)  # Weekly std dev
        else:
            std_dev = 1.0

        if std_dev == 0:
            std_dev = 0.001  # Avoid division by zero

        deviation_sigma = (this_week_count - weekly_baseline_avg) / std_dev

        if abs(deviation_sigma) >= sigma_threshold:
            anomalies.append({
                "category": cat,
                "this_week": this_week_count,
                "baseline_avg": round(weekly_baseline_avg, 1),
                "deviation_sigma": round(deviation_sigma, 2),
                "direction": "surge" if deviation_sigma > 0 else "drop",
            })

    # Sort by absolute deviation descending
    anomalies.sort(key=lambda x: abs(x["deviation_sigma"]), reverse=True)

    return {
        "anomalies": anomalies,
        "sigma_threshold": sigma_threshold,
        "this_week_days": this_week_days,
        "baseline_days": baseline_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }