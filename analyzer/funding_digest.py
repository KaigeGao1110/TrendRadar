"""Funding Digest — generate summary reports from all analysis modules."""

import os
import sys
from datetime import datetime, timezone

# Add project root to path when running directly
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from analyzer.funding import (
    generate_heatmap,
    get_big_rounds,
    detect_emerging,
    calculate_pricing_anchors,
    detect_anomalies,
    cluster_niches,
)


def generate_funding_digest(
    csv_path: str,
    output_dir: str = os.path.expanduser("~/Projects/TrendRadar/funding-analysis"),
    big_round_threshold_m: float = 50.0,
) -> str:
    """Generate a comprehensive funding analysis report in Markdown.

    Args:
        csv_path: Path to funding.csv.
        output_dir: Directory to save the report.
        big_round_threshold_m: Threshold for big rounds in millions.

    Returns:
        Path to the generated report file.
    """
    # Run all analyses
    heatmap = generate_heatmap(csv_path)
    big_rounds = get_big_rounds(csv_path, threshold_m=big_round_threshold_m)
    emerging = detect_emerging(csv_path)
    anchors = calculate_pricing_anchors(csv_path)
    anomalies = detect_anomalies(csv_path)
    niches = cluster_niches(csv_path)

    # Build report
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_lines = [
        f"# Funding Analysis — {today}",
        "",
        f"**Generated at:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "---",
        "",
    ]

    # 1. Category Heatmap (Top 10)
    report_lines.append("## 🔥 类别热力图 (Top 10)\n")
    top_10 = heatmap["heatmap"][:10]
    if top_10:
        report_lines.append("| Category | Count | Total Funding ($M) | Heat Score |")
        report_lines.append("|----------|-------|-------------------|------------|")
        for item in top_10:
            report_lines.append(
                f"| {item['category']} | {item['count']} | "
                f"${item['total_funding_m']:,.1f}M | {item['heat_score']:.1f} |"
            )
    else:
        report_lines.append("_No data available._")
    report_lines.append("")

    # 2. Big Rounds (>= threshold)
    report_lines.append(f"## 💰 大额融资 (≥${big_round_threshold_m:.0f}M)\n")
    if big_rounds["big_rounds"]:
        report_lines.append(f"**Total:** {big_rounds['total']} rounds\n")
        report_lines.append("| Company | Amount | Valuation | Categories |")
        report_lines.append("|---------|--------|-----------|------------|")
        for r in big_rounds["big_rounds"][:20]:  # Top 20
            val_str = f"${r['valuation_b']:.2f}B" if r.get("valuation_b") else "-"
            cats = ", ".join(r["categories"][:2]) if r["categories"] else "-"
            report_lines.append(
                f"| [{r['company']}]({r['url']}) | "
                f"${r['amount_m']:,.0f}M | {val_str} | {cats} |"
            )
    else:
        report_lines.append("_No big rounds found._")
    report_lines.append("")

    # 3. Emerging Trends
    report_lines.append("## 📈 新兴趋势\n")
    emerging_cats = [e for e in emerging["emerging"] if e["growth_rate"] != 'inf' and float(e['growth_rate']) > 1.0][:10]
    if emerging_cats:
        report_lines.append("| Category | This Week | Baseline Avg | Growth Rate |")
        report_lines.append("|----------|-----------|--------------|-------------|")
        for e in emerging_cats:
            report_lines.append(
                f"| {e['category']} | {e['this_week']} | "
                f"{e['baseline_avg']:.1f} | {float(e['growth_rate']):.2f}x |"
            )
    else:
        report_lines.append("_No significant emerging trends detected._")
    report_lines.append("")

    # 4. Niche Clustering
    report_lines.append("## 🎯 Niche Clustering\n")
    top_niches = [n for n in niches["niches"] if n.get("company_count", n.get("count", 0)) > 0][:15]
    if top_niches:
        report_lines.append("| Niche | Parent | Count | This Week | Total Funding ($M) | Growth Rate |")
        report_lines.append("|-------|--------|-------|-----------|-------------------|-------------|")
        for n in top_niches:
            if n["growth_rate_pct"] == float("inf"):
                growth_str = "∞"
            else:
                growth_str = f"{n['growth_rate_pct']:.1f}%"
            report_lines.append(
                f"| {n['niche']} | {n['parent_category']} | {n['count']} | "
                f"{n['this_week_count']} | ${n['total_funding_m']:,.1f}M | {growth_str} {n['growth_emoji']} |"
            )
    else:
        report_lines.append("_No niche matches found._")
    report_lines.append("")

    # 5. Pricing Anchors
    report_lines.append("## 💵 估值锚点\n")
    anchors_data = anchors.get("anchors", {})
    top_anchors = dict(list(anchors_data.items())[:10])
    if top_anchors:
        report_lines.append("| Category | Count | Min ($M) | Median ($M) | Max ($M) | P25 | P75 |")
        report_lines.append("|----------|-------|-----------|--------------|----------|-----|-----|")
        for cat, stats in top_anchors.items():
            report_lines.append(
                f"| {cat} | {stats['count']} | ${stats['min_m']:.0f} | "
                f"${stats['median_m']:.0f} | ${stats['max_m']:.0f} | "
                f"${stats['p25_m']:.0f} | ${stats['p75_m']:.0f} |"
            )
    else:
        report_lines.append("_No valuation data available._")
    report_lines.append("")

    # 6. Trend Comparison (requires historical data — placeholder)
    report_lines.append("## 📊 趋势变化\n")
    report_lines.append("_Requires historical heatmap snapshots for comparison._\n")
    report_lines.append("")

    # 7. Anomaly Detection
    report_lines.append("## 🚨 异常检测\n")
    if anomalies["anomalies"]:
        report_lines.append("| Category | This Week | Baseline Avg | Deviation (σ) | Direction |")
        report_lines.append("|----------|-----------|--------------|---------------|-----------|")
        for a in anomalies["anomalies"][:10]:
            sigma = a["deviation_sigma"]
            emoji = "📈" if sigma != 'inf' and sigma > 0 else "📉"
            sigma_str = f"{sigma:.1f}σ" if sigma != 'inf' else "∞"
            report_lines.append(
                f"| {a['category']} | {a['this_week']} | "
                f"{a['baseline_avg']:.1f} | {sigma_str} | {emoji} |"
            )
    else:
        report_lines.append("_No significant anomalies detected._")
    report_lines.append("")

    report_lines.append("---\n")
    report_lines.append(f"_Report generated by TrendRadar Funding Analysis Engine_\n")

    # Save report
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"{today}.md")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    return report_path


if __name__ == "__main__":
    # Quick test
    csv_path = os.path.expanduser("~/Projects/TrendRadar/output/funding.csv")
    if os.path.exists(csv_path):
        report_path = generate_funding_digest(csv_path)
        print(f"Report saved to: {report_path}")
    else:
        print("CSV file not found:", csv_path)