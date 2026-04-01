"""AI-powered trend analysis across all data sources."""

import os
import json
import re
from typing import Optional
from collections import Counter

# Try to get API key from environment
try:
    import anthropic
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
except ImportError:
    client = None
    ANTHROPIC_API_KEY = ""


def analyze_daily_trends(all_data: dict) -> dict:
    """Cross-source trend analysis.

    Takes data from all 4 sources and identifies:
    1. Hot categories (appearing in multiple sources)
    2. Emerging patterns (new trends not seen before)
    3. VC interest signals (funding + YC + PH overlap)
    4. Technology shifts (HN trends + VC funding correlation)

    Args:
        all_data: {source_name: [items]}

    Returns:
        {hot_categories[], emerging_patterns[], recommendations[], raw_analysis}
    """
    # Always use heuristic first (fast, reliable)
    heuristic = _heuristic_analysis(all_data)

    # If LLM available, enhance with AI analysis
    if client and ANTHROPIC_API_KEY:
        try:
            llm_result = _llm_analysis(all_data, heuristic)
            if llm_result:
                return llm_result
        except Exception:
            pass

    return heuristic


def _llm_analysis(all_data: dict, heuristic: dict) -> Optional[dict]:
    """Enhance heuristic analysis with LLM."""
    # Build detailed summaries
    summaries = {}
    for source, items in all_data.items():
        summaries[source] = _summarize_items_detailed(items)

    prompt = f"""Analyze startup/VC trend data and give SPECIFIC, CONCRETE insights.

DATA:
{_format_source_summaries(summaries)}

HEURISTIC ANALYSIS (enhance, don't replace):
- Hot categories: {heuristic.get('hot_categories', [])}
- Signals: {heuristic.get('vc_signals', [])}

Give me SPECIFIC insights with COMPANY NAMES. For each hot category, name 1-2 specific companies/products that represent it.
For recommendations, give 2-3 concrete, actionable ideas based on what's actually trending RIGHT NOW.

Respond with JSON only:
{{
  "hot_categories": ["specific category — why, with company examples"],
  "emerging_patterns": ["specific pattern with evidence"],
  "vc_signals": ["specific sector with named funding rounds"],
  "recommendations": ["concrete action idea based on real trend"],
  "raw_insights": "brief analysis"
}}
"""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text if response.content else "{}"
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        result = json.loads(json_match.group())
        return {
            "hot_categories": result.get("hot_categories", heuristic.get("hot_categories", [])),
            "emerging_patterns": result.get("emerging_patterns", []),
            "vc_signals": result.get("vc_signals", heuristic.get("vc_signals", [])),
            "recommendations": result.get("recommendations", heuristic.get("recommendations", [])),
            "raw_analysis": result.get("raw_insights", ""),
        }
    return None


def _heuristic_analysis(all_data: dict) -> dict:
    """Heuristic analysis using real data — no hardcoded fallbacks."""
    yc_data = all_data.get("ycombinator", [])
    ph_data = all_data.get("producthunt", [])
    hn_data = all_data.get("hackernews", [])
    vc_data = all_data.get("vc_funding", [])

    # --- YC Analysis ---
    yc_categories = Counter()
    yc_companies = []
    for company in _unwrap_list(yc_data):
        name = company.get("name", "")
        one_liner = company.get("one_liner", "")
        industries = company.get("industry", company.get("industries", []))
        tags = company.get("tags", [])
        if isinstance(industries, str):
            industries = [industries]
        yc_companies.append(f"{name}: {one_liner[:60]}")
        for ind in industries:
            if ind and isinstance(ind, str):
                yc_categories[ind] += 1
        for tag in tags:
            if tag and isinstance(tag, str):
                yc_categories[tag] += 1

    # --- PH Analysis ---
    ph_topics = Counter()
    ph_products = []
    for product in _unwrap_list(ph_data):
        name = product.get("name", "")
        tagline = product.get("tagline", "")
        topics = product.get("topics", [])
        ph_products.append(f"{name}: {tagline[:60]}")
        for topic in topics:
            if topic and topic != "General":
                ph_topics[topic] += 1

    # --- HN Analysis ---
    hn_stories = []
    for story in _unwrap_list(hn_data):
        title = story.get("title", "")
        score = story.get("score", 0)
        if title:
            hn_stories.append({"title": title, "score": score})

    # Sort HN by score
    hn_stories.sort(key=lambda x: x["score"], reverse=True)
    hn_top = [s["title"] for s in hn_stories[:10]]

    # --- VC Funding Analysis ---
    vc_sectors = Counter()
    vc_rounds = []
    for round_data in _unwrap_list(vc_data):
        company = round_data.get("company", "")
        amount = round_data.get("amount", "")
        sector = round_data.get("sector", "")
        if sector:
            vc_sectors[sector] += 1
        if company and amount:
            vc_rounds.append(f"{company}: {amount}")

    # --- Build hot categories from REAL data ---
    hot_categories = []

    # Cross-source: if a category appears in YC + PH or YC + VC, it's hot
    yc_set = set(yc_categories.keys())
    ph_set = set(ph_topics.keys())
    vc_set = set(vc_sectors.keys())

    # Direct from YC (most reliable signal)
    for cat, count in yc_categories.most_common(5):
        sources = ["YC"]
        if cat in ph_set:
            sources.append("PH")
        if cat in vc_set:
            sources.append("VC")
        label = f"{cat}" + (f" ({' + '.join(sources)})" if len(sources) > 1 else "")
        hot_categories.append(label)

    # If YC data is thin, supplement from PH
    if len(hot_categories) < 3:
        for topic, count in ph_topics.most_common(5):
            if topic not in [c.split(" (")[0] for c in hot_categories]:
                hot_categories.append(f"{topic} (PH: {count} products)")

    # --- Build VC signals from REAL data ---
    vc_signals = []
    for sector, count in vc_sectors.most_common(3):
        examples = [r for r in vc_rounds if sector.lower() in r.lower()][:2]
        signal = f"{sector}: {count} rounds"
        if examples:
            signal += f" ({'; '.join(examples)})"
        vc_signals.append(signal)

    # --- Build recommendations from REAL data ---
    recommendations = []

    # YC-based recommendations
    if yc_companies:
        top_yc = yc_categories.most_common(1)
        if top_yc:
            cat = top_yc[0][0]
            examples = [c for c in yc_companies if cat.lower() in c.lower()][:2]
            recommendations.append(f"YC is betting on {cat} — look at: {'; '.join(examples[:2])}")

    # HN-based recommendations
    if hn_top:
        # Find common themes in top HN stories
        hn_text = " ".join(hn_top).lower()
        if "ai" in hn_text or "llm" in hn_text:
            recommendations.append(f"HN is buzzing about AI — top story: \"{hn_top[0][:80]}\"")
        elif "security" in hn_text or "vulnerability" in hn_text:
            recommendations.append(f"Security is trending on HN — top story: \"{hn_top[0][:80]}\"")
        else:
            recommendations.append(f"HN top trend: \"{hn_top[0][:80]}\"")

    # PH-based recommendations
    if ph_products:
        recommendations.append(f"Today's #1 Product Hunt: {ph_products[0]}")

    # VC-based recommendations
    if vc_rounds:
        recommendations.append(f"Latest funding: {vc_rounds[0]}")

    # Build emerging patterns from HN
    emerging_patterns = []
    for story in hn_stories[:5]:
        emerging_patterns.append(story["title"][:100])

    if not hot_categories:
        hot_categories = ["No cross-source signals detected today"]

    return {
        "hot_categories": hot_categories[:5],
        "emerging_patterns": emerging_patterns[:5],
        "vc_signals": vc_signals[:5],
        "recommendations": recommendations[:5],
        "raw_analysis": "Heuristic analysis from real data",
    }


def _unwrap_list(data) -> list:
    """Unwrap nested data structures to get a flat list of dicts."""
    if isinstance(data, list):
        if not data:
            return []
        result = []
        for item in data:
            if isinstance(item, dict):
                if "data" in item and isinstance(item["data"], list):
                    result.extend(item["data"])
                elif "data" in item and isinstance(item["data"], dict):
                    result.append(item["data"])
                else:
                    result.append(item)
            elif isinstance(item, list):
                result.extend(item)
        return result
    elif isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            return data["data"]
        return [data]
    return []


def generate_trend_summary(trends: dict) -> str:
    """Generate a concise trend summary."""
    lines = [
        "# 🔥 TrendRadar Daily",
        "",
        "## Hot Categories",
    ]
    for cat in trends.get("hot_categories", [])[:5]:
        lines.append(f"- {cat}")

    if trends.get("vc_signals"):
        lines.extend(["", "## VC Funding Signals"])
        for signal in trends.get("vc_signals", [])[:5]:
            lines.append(f"- {signal}")

    if trends.get("emerging_patterns"):
        lines.extend(["", "## Trending Now"])
        for pattern in trends.get("emerging_patterns", [])[:5]:
            lines.append(f"- {pattern}")

    if trends.get("recommendations"):
        lines.extend(["", "## For Founders"])
        for rec in trends.get("recommendations", [])[:5]:
            lines.append(f"- {rec}")

    return "\n".join(lines)


def _summarize_items_detailed(items) -> str:
    """Summarize items with names + descriptions for LLM."""
    items = _unwrap_list(items)
    lines = []
    for item in items[:15]:
        if isinstance(item, dict):
            name = item.get("name", item.get("title", item.get("company", "")))
            desc = item.get("one_liner", item.get("tagline", item.get("description", "")))
            if name:
                line = f"- {name}"
                if desc:
                    line += f": {desc[:80]}"
                lines.append(line)
    return "\n".join(lines) if lines else "No data"


def _format_source_summaries(summaries: dict) -> str:
    """Format source summaries."""
    lines = []
    for source, summary in summaries.items():
        lines.append(f"\n### {source.upper()}")
        lines.append(summary)
    return "\n".join(lines)
