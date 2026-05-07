"""Niche Clustering — group funding records into niches via category combinations."""

from datetime import datetime, timezone, timedelta

from analyzer.funding.parser import load_funding_csv

# Predefined category combination → (niche_name, parent_category).
# Keys are sorted tuples so order doesn't matter.
_RAW_COMBINATIONS = [
    (("Artificial Intelligence", "Developer Tools"), ("AI Code Tools", "Artificial Intelligence")),
    (("Artificial Intelligence", "Cloud Computing"), ("AI Infrastructure", "Artificial Intelligence")),
    (("Artificial Intelligence", "Transportation"), ("AI Autonomous Driving", "Artificial Intelligence")),
    (("Artificial Intelligence", "Hardware"), ("AI Chips & Hardware", "Artificial Intelligence")),
    (("Artificial Intelligence", "Fintech"), ("AI Fintech", "Artificial Intelligence")),
    (("Artificial Intelligence", "Cybersecurity"), ("AI Security", "Artificial Intelligence")),
    (("Artificial Intelligence", "Healthtech"), ("AI Health & Bio", "Artificial Intelligence")),
    (("Artificial Intelligence", "Biotech"), ("AI Health & Bio", "Artificial Intelligence")),
    (("Artificial Intelligence", "SaaS"), ("AI SaaS", "Artificial Intelligence")),
    (("Artificial Intelligence", "Data & Analytics"), ("AI Data & Analytics", "Artificial Intelligence")),
    (("SaaS", "Developer Tools"), ("Developer SaaS", "SaaS")),
    (("SaaS", "Fintech"), ("Fintech SaaS", "SaaS")),
    (("SaaS", "Enterprise Software"), ("Enterprise SaaS", "SaaS")),
    (("Fintech", "Payments"), ("Payment Infrastructure", "Fintech")),
    (("Cloud Computing", "Developer Tools"), ("Cloud DevOps", "Cloud Computing")),
    (("Climate Tech", "Hardware"), ("Climate Hardware", "Climate Tech")),
    (("Cybersecurity", "Cloud Computing"), ("Cloud Security", "Cybersecurity")),
    (("Aerospace", "Hardware"), ("Space & Aerospace", "Aerospace")),
    (("Blockchain & Crypto", "Fintech"), ("Crypto Fintech", "Fintech")),
]

# Normalize keys to sorted tuples for order-agnostic lookups
NICHE_COMBINATIONS = {
    tuple(sorted(k)): v for k, v in _RAW_COMBINATIONS
}


def _get_niche_for_record(categories: list[str]) -> tuple[str, str] | None:
    """Return (niche_name, parent_category) for a record's categories, or None."""
    if not categories:
        return None

    # Normalize: deduplicate, strip, and sort
    cats = sorted({c.strip() for c in categories if c.strip()})
    if not cats:
        return None

    combo = tuple(cats)

    # Try exact combination match first
    if combo in NICHE_COMBINATIONS:
        return NICHE_COMBINATIONS[combo]

    # Try subset combinations (for multi-category records where a pair matches)
    if len(cats) > 2:
        from itertools import combinations
        for r in range(2, len(cats)):
            for sub in combinations(cats, r):
                sub_combo = tuple(sorted(sub))
                if sub_combo in NICHE_COMBINATIONS:
                    return NICHE_COMBINATIONS[sub_combo]

    # Single category → use the category itself as the niche
    if len(cats) == 1:
        return cats[0], cats[0]

    # Fallback: generic combination name
    generic = " + ".join(cats)
    return generic, cats[0]


def cluster_niches(
    csv_path: str,
    this_week_days: int = 7,
    baseline_days: int = 30,
) -> dict:
    """Cluster funding records into niches based on category combinations.

    Args:
        csv_path: Path to funding.csv.
        this_week_days: Days for "this week" window.
        baseline_days: Days for baseline window.

    Returns:
        Dict with 'niches' list sorted by growth_rate_pct descending.
    """
    records = load_funding_csv(csv_path)
    now = datetime.now(timezone.utc)
    this_week_start = now - timedelta(days=this_week_days)
    baseline_start = now - timedelta(days=baseline_days)

    # niche_name -> stats
    niche_stats: dict[str, dict] = {}

    for rec in records:
        result = _get_niche_for_record(rec["categories"])
        if result is None:
            continue
        niche_name, parent = result

        if niche_name not in niche_stats:
            niche_stats[niche_name] = {
                "count": 0,
                "company_count": 0,
                "this_week_count": 0,
                "baseline_count": 0,
                "total_funding_m": 0.0,
                "parent_category": parent,
            }

        stats = niche_stats[niche_name]
        stats["count"] += 1
        stats["company_count"] += 1
        stats["total_funding_m"] += rec["amount_m"]

        first_seen = rec.get("first_seen_at_dt")
        if first_seen:
            if first_seen >= this_week_start:
                stats["this_week_count"] += 1
            elif baseline_start <= first_seen < this_week_start:
                stats["baseline_count"] += 1

    niches = []
    for niche_name, stats in niche_stats.items():
        # Only include niches with >= 2 companies
        if stats["count"] < 2:
            continue

        baseline_daily_avg = stats["baseline_count"] / baseline_days if stats["baseline_count"] else 0.0

        if baseline_daily_avg > 0:
            growth_rate_pct = (stats["this_week_count"] / baseline_daily_avg - 1) * 100
        elif stats["this_week_count"] > 0:
            growth_rate_pct = float("inf")
        else:
            growth_rate_pct = 0.0

        if growth_rate_pct == float("inf") or growth_rate_pct >= 25:
            growth_emoji = "🔥🔥"
        elif growth_rate_pct >= 15:
            growth_emoji = "🔥"
        else:
            growth_emoji = ""

        niches.append({
            "niche": niche_name,
            "parent_category": stats["parent_category"],
            "count": stats["count"],
            "company_count": stats["company_count"],
            "this_week_count": stats["this_week_count"],
            "baseline_count": stats["baseline_count"],
            "baseline_daily_avg": round(baseline_daily_avg, 2),
            "total_funding_m": round(stats["total_funding_m"], 1),
            "growth_rate_pct": growth_rate_pct,
            "growth_emoji": growth_emoji,
        })

    niches.sort(key=lambda x: x["growth_rate_pct"], reverse=True)

    return {
        "niches": niches,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
