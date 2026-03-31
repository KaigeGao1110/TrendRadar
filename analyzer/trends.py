"""AI-powered trend analysis across all data sources."""

import os
from typing import Optional

import anthropic

# Try to get API key from environment
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


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
    # If no API key, use heuristic analysis
    if not client or not ANTHROPIC_API_KEY:
        return _heuristic_analysis(all_data)
    
    # Build summary of each source
    source_summaries = {}
    for source, items in all_data.items():
        if isinstance(items, list) and items:
            if isinstance(items[0], dict) and "data" in items[0]:
                # Snapshot format
                items = [item["data"] for item in items]
            source_summaries[source] = _summarize_items(items)
        elif isinstance(items, dict):
            source_summaries[source] = _summarize_items([items])
    
    prompt = f"""Analyze the following startup/VC trend data from multiple sources and identify:

1. HOT CATEGORIES: Categories appearing in multiple sources (high signal)
2. EMERGING PATTERNS: New or accelerating trends
3. VC INTEREST SIGNALS: Sectors with funding activity + YC + PH overlap
4. KEY RECOMMENDATIONS: Actionable insights for founders/indie hackers

DATA SUMMARY:
{_format_source_summaries(source_summaries)}

Respond with JSON:
{{
  "hot_categories": ["category name with brief justification"],
  "emerging_patterns": ["pattern description"],
  "vc_signals": ["sector with funding evidence"],
  "recommendations": ["actionable recommendation for founders"],
  "raw_insights": "detailed analysis text"
}}
"""

    try:
        response = client.messages.create(
            model="claude-opus-4-20241120",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        import json
        import re
        
        text = response.content[0].text if response.content else "{}"
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return {
                "hot_categories": result.get("hot_categories", []),
                "emerging_patterns": result.get("emerging_patterns", []),
                "vc_signals": result.get("vc_signals", []),
                "recommendations": result.get("recommendations", []),
                "raw_analysis": result.get("raw_insights", text),
            }
    except Exception:
        pass
    
    return _heuristic_analysis(all_data)


def _heuristic_analysis(all_data: dict) -> dict:
    """Fallback heuristic analysis without LLM."""
    hot_categories = []
    patterns = []
    recommendations = []
    
    # Analyze each source for signals
    source_signals = {}
    
    for source, data in all_data.items():
        if isinstance(data, list) and data:
            if isinstance(data[0], dict):
                items = data[0].get("data", data[0]) if "data" in data[0] else data[0]
                signals = _extract_signals(items)
                source_signals[source] = signals
        elif isinstance(data, dict):
            source_signals[source] = _extract_signals([data])
    
    # Cross-source analysis
    all_categories = set()
    for signals in source_signals.values():
        all_categories.update(signals.get("categories", []))
    
    for cat in all_categories:
        count = sum(1 for s in source_signals.values() if cat in s.get("categories", []))
        if count >= 2:
            hot_categories.append(f"{cat} (appearing in {count} sources)")
    
    # Generate recommendations
    if "AI/ML" in all_categories or "AI" in str(source_signals):
        recommendations.append("AI tooling remains hot — focus on specific verticals or workflows rather than general platforms")
    if "SaaS" in all_categories:
        recommendations.append("B2B SaaS continues to attract funding — look for underserved niches")
    if "Climate/Tech" in all_categories or "Climate" in str(source_signals):
        recommendations.append("Climate tech funding accelerating — hardware + software combos getting attention")
    
    if not hot_categories:
        hot_categories = ["AI/ML applications", "Developer tools", "B2B SaaS"]
    if not recommendations:
        recommendations = ["Monitor YC batch trends for emerging patterns", "Track HN for technology shifts"]
    
    return {
        "hot_categories": hot_categories[:5],
        "emerging_patterns": patterns[:5],
        "vc_signals": [f"{cat} showing strong signal" for cat in hot_categories[:3]],
        "recommendations": recommendations[:5],
        "raw_analysis": "Heuristic analysis (no LLM API key configured)",
    }


def generate_trend_summary(trends: dict) -> str:
    """Generate a concise trend summary.
    
    Returns: Markdown-formatted summary suitable for Slack/email.
    """
    lines = [
        "# 🔥 TrendRadar Daily Summary",
        "",
        "## Hot Categories",
    ]
    
    for cat in trends.get("hot_categories", [])[:5]:
        lines.append(f"- {cat}")
    
    lines.extend(["", "## Emerging Patterns"])
    for pattern in trends.get("emerging_patterns", [])[:5]:
        lines.append(f"- {pattern}")
    
    lines.extend(["", "## VC Signals"])
    for signal in trends.get("vc_signals", [])[:5]:
        lines.append(f"- {signal}")
    
    lines.extend(["", "## Recommendations"])
    for rec in trends.get("recommendations", [])[:5]:
        lines.append(f"- {rec}")
    
    return "\n".join(lines)


def _summarize_items(items: list) -> str:
    """Summarize a list of items for the LLM prompt."""
    if not items:
        return "No data"
    
    names = []
    for item in items[:20]:
        if isinstance(item, dict):
            name = item.get("name", item.get("title", item.get("company", "")))
            if name:
                names.append(name)
        elif isinstance(item, str):
            names.append(item)
    
    return ", ".join(names[:15]) if names else "No clear names"


def _format_source_summaries(summaries: dict) -> str:
    """Format source summaries for the prompt."""
    lines = []
    for source, summary in summaries.items():
        lines.append(f"\n### {source.upper()}")
        lines.append(f"Items: {summary}")
    return "\n".join(lines)


def _extract_signals(items: list) -> dict:
    """Extract signals from a list of items."""
    categories = set()
    keywords = []
    
    for item in items:
        if isinstance(item, dict):
            text = " ".join(str(v) for v in item.values()).lower()
            
            # Category detection
            if "ai" in text or "ml" in text or "machine learning" in text:
                categories.add("AI/ML")
            if "fintech" in text or "payment" in text or "banking" in text:
                categories.add("Fintech")
            if "health" in text or "medical" in text or "bio" in text:
                categories.add("Healthcare")
            if "saas" in text or "b2b" in text or "enterprise" in text:
                categories.add("SaaS")
            if "climate" in text or "energy" in text or "solar" in text:
                categories.add("Climate/Tech")
            if "security" in text or "cyber" in text:
                categories.add("Cybersecurity")
            if "dev" in text or "api" in text or "tool" in text:
                categories.add("Developer Tools")
    
    return {"categories": list(categories), "keywords": keywords}
