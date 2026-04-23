"""LLM-based reasoning and suggested action generation.

Uses Anthropic Claude for generating human-readable analysis.
"""

import os
from typing import Optional


DEFAULT_REASONING_PROMPT = """You are TrendRadar AI, an analyst specializing in startup opportunity detection.

Given the following startup/product event, provide a concise reasoning for why this is (or isn't) a good opportunity.

EVENT:
{event_text}

SCORE BREAKDOWN:
- Pain Density: {pain_density}/100 — {pain_density_desc}
- Tech Feasibility: {tech_feasibility}/100 — {tech_feasibility_desc}
- Timing: {timing}/100 — {timing_desc}

OPPORTUNITY TYPE: {opportunity_type}
IMITATION DIFFICULTY: {imitation_difficulty}

Based on the above, write 2-3 sentences explaining:
1. What the core opportunity is
2. Why the timing is good or bad
3. What makes this easy or hard to imitate

Keep your response concise and actionable. Focus on what matters for a solo founder.
"""

DEFAULT_SUGGESTED_ACTION_PROMPT = """You are TrendRadar AI, a startup opportunity advisor for solo founders.

OPPORTUNITY TYPE: {opportunity_type}
IMITATION DIFFICULTY: {imitation_difficulty}
TOTAL SCORE: {total_score}/100

EVENT SUMMARY:
{event_text}

Based on this opportunity:
1. What is the single most important next step?
2. What is the fastest way to validate this opportunity?
3. What tech stack would you recommend for a v1?

Respond with a JSON object:
{{
  "next_step": "1-2 sentence concrete action",
  "validation_path": "How to quickly validate demand",
  "recommended_stack": ["Tech1", "Tech2", "Tech3"]
}}
"""


def generate_reasoning(
    anthropic_client,
    event_text: str,
    score_breakdown: dict,
    opportunity_type: str,
    imitation_difficulty: str,
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """Generate reasoning text via LLM call.

    Args:
        anthropic_client: Anthropic client instance
        event_text: Combined event text for analysis
        score_breakdown: Score breakdown dict
        opportunity_type: One of fast_follow, innovation, infrastructure, meta_tool
        imitation_difficulty: easy, medium, or hard

    Returns:
        Reasoning text (2-3 sentences)
    """
    if not anthropic_client:
        return _fallback_reasoning(score_breakdown, opportunity_type, imitation_difficulty)

    pain_density = score_breakdown.get("pain_density", 0)
    tech_feasibility = score_breakdown.get("tech_feasibility", 0)
    timing = score_breakdown.get("timing", 0)

    pain_density_desc = _dimension_desc("pain_density", pain_density)
    tech_feasibility_desc = _dimension_desc("tech_feasibility", tech_feasibility)
    timing_desc = _dimension_desc("timing", timing)

    prompt = DEFAULT_REASONING_PROMPT.format(
        event_text=event_text[:1000],
        pain_density=pain_density,
        pain_density_desc=pain_density_desc,
        tech_feasibility=tech_feasibility,
        tech_feasibility_desc=tech_feasibility_desc,
        timing=timing,
        timing_desc=timing_desc,
        opportunity_type=opportunity_type,
        imitation_difficulty=imitation_difficulty,
    )

    try:
        response = anthropic_client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text if response.content else ""
        return text.strip()
    except Exception as e:
        print(f"LLM reasoning error: {e}")
        return _fallback_reasoning(score_breakdown, opportunity_type, imitation_difficulty)


def generate_suggested_action(
    anthropic_client,
    event_text: str,
    opportunity_type: str,
    imitation_difficulty: str,
    total_score: int,
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """Generate suggested action text via LLM call.

    Args:
        anthropic_client: Anthropic client instance
        event_text: Combined event text
        opportunity_type: One of fast_follow, innovation, infrastructure, meta_tool
        imitation_difficulty: easy, medium, or hard
        total_score: Overall score 0-100

    Returns:
        Suggested action text
    """
    if not anthropic_client:
        return _fallback_suggested_action(opportunity_type, imitation_difficulty)

    prompt = DEFAULT_SUGGESTED_ACTION_PROMPT.format(
        opportunity_type=opportunity_type,
        imitation_difficulty=imitation_difficulty,
        total_score=total_score,
        event_text=event_text[:1000],
    )

    try:
        response = anthropic_client.messages.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text if response.content else ""

        # Try to parse as JSON
        import re, json
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            next_step = data.get("next_step", "")
            if next_step:
                return next_step

        return text.strip()
    except Exception as e:
        print(f"LLM suggested_action error: {e}")
        return _fallback_suggested_action(opportunity_type, imitation_difficulty)


def _dimension_desc(dimension: str, score: int) -> str:
    """Get human-readable description for a score dimension."""
    if dimension == "pain_density":
        if score >= 80:
            return "Strong multi-source pain signals"
        elif score >= 60:
            return "Pain mentioned in multiple sources"
        elif score >= 40:
            return "Single-source acute pain"
        else:
            return "Weak or vague pain signal"
    elif dimension == "tech_feasibility":
        if score >= 80:
            return "Simple API-based implementation"
        elif score >= 60:
            return "Moderate complexity, achievable solo"
        elif score >= 40:
            return "Some novel tech required"
        else:
            return "Significant technical complexity"
    elif dimension == "timing":
        if score >= 80:
            return "Recent and accelerating signals"
        elif score >= 60:
            return "Recent stable signals"
        elif score >= 40:
            return "Moderate-age signals"
        else:
            return "Old or saturated signals"
    return "Unknown"


def _fallback_reasoning(score_breakdown: dict, opp_type: str, imitation_diff: str) -> str:
    """Generate basic reasoning without LLM."""
    pain = score_breakdown.get("pain_density", 0)
    tech = score_breakdown.get("tech_feasibility", 0)
    timing = score_breakdown.get("timing", 0)

    parts = []
    if pain >= 70:
        parts.append("Strong pain signal detected across multiple sources.")
    elif pain >= 40:
        parts.append("Moderate pain signal present.")

    if tech >= 70:
        parts.append("Implementation appears straightforward with existing APIs.")
    elif tech < 40:
        parts.append("Technical complexity may be a barrier.")

    if timing >= 70:
        parts.append("Timing is favorable — signals are recent.")
    elif timing < 40:
        parts.append("Timing may be late — market could be saturated.")

    if not parts:
        parts.append(f"This is a {opp_type} opportunity with {imitation_diff} imitation difficulty.")

    return " ".join(parts)


def _fallback_suggested_action(opp_type: str, imitation_diff: str) -> str:
    """Generate basic suggested action without LLM."""
    if opp_type == "fast_follow":
        base = "Validate demand by reaching out to 5 potential users in the target market."
    elif opp_type == "innovation":
        base = "Build a quick prototype to test the novel approach with early adopters."
    elif opp_type == "infrastructure":
        base = "Create a minimal working example and publish as open source to gauge developer interest."
    else:
        base = "Research the problem space and identify the most painful unsolved aspect."

    if imitation_diff == "easy":
        return f"{base} Since imitation is easy, move fast and ship a v1 within 2 weeks."
    elif imitation_diff == "hard":
        return f"{base} Focus on building a unique data moat or community to create defensibility."
    else:
        return f"{base} Aim to ship v1 within 3-4 weeks."
