"""Scoring pipeline for TrendRadar opportunities.

Implements pain_density (40%), tech_feasibility (30%), timing (30%) scoring
formulas from PRD-v2.md Section 7.3.
"""

import math
from datetime import datetime, timezone
from typing import Optional


def compute_total_score(score_breakdown: dict) -> int:
    """Compute overall score from breakdown.

    total_score = round(pain_density × 0.4 + tech_feasibility × 0.3 + timing × 0.3)

    Args:
        score_breakdown: {"pain_density": N, "tech_feasibility": N, "timing": N}

    Returns:
        Integer score 0-100
    """
    pain = score_breakdown.get("pain_density", 0)
    tech = score_breakdown.get("tech_feasibility", 0)
    timing = score_breakdown.get("timing", 0)
    return round(pain * 0.4 + tech * 0.3 + timing * 0.3)


def compute_pain_density(event: dict) -> int:
    """Compute pain density score (0-100).

    Scoring rules (PRD Section 7.3):
    - 80-100: Multiple independent sources (≥3) explicitly describe the same pain
    - 60-79: Same pain mentioned in 2 sources
    - 40-59: Pain mentioned in 1 source but described as acute
    - 0-39: Vague or niche pain, weak signal
    """
    keywords = event.get("keywords", [])
    signal_count = event.get("signal_count", 1)
    severity = event.get("severity", 5)
    description = event.get("description", "") or ""

    if isinstance(keywords, list):
        pain_word_count = sum(
            1 for kw in keywords
            if any(w in kw.lower() for w in ["pain", "struggle", "problem", "frustrat", "annoying", "hard", "difficult", "expensive", "broken"])
        )
    else:
        pain_word_count = 0

    # Multiple independent sources (signal_count reflects cross-source mentions)
    if signal_count >= 3 and pain_word_count >= 2:
        return min(100, 80 + min(20, pain_word_count * 5))
    elif signal_count >= 2 and pain_word_count >= 1:
        return min(79, 60 + min(19, pain_word_count * 5))
    elif signal_count >= 1 and severity >= 7:
        return min(59, 40 + min(19, severity * 3))
    elif pain_word_count > 0:
        return min(39, 20 + pain_word_count * 5)
    else:
        return min(39, severity * 5)


def compute_tech_feasibility(event: dict) -> int:
    """Compute tech feasibility score (0-100).

    Scoring rules (PRD Section 7.3):
    - 80-100: No deep tech required, can use existing APIs/frameworks
    - 60-79: Moderate complexity, 1-2 novel integrations
    - 40-59: Some novel tech, but achievable solo
    - 0-39: Requires significant ML/infra work, large data sets, or complex domain expertise
    """
    keywords = event.get("keywords", []) or []
    categories = event.get("categories", []) or []
    description = (event.get("description", "") or "").lower()

    all_text = " ".join(keywords + categories).lower() + " " + description

    # Hard tech indicators (reduce score)
    hard_tech = ["ml", "machine learning", "deep learning", "neural", "nlp", "cv",
                 "blockchain", "crypto", "security", "encryption", "complex",
                 "infrastructure", "distributed", "real-time", "streaming"]
    easy_tech = ["llm", "api", "saas", "openai", "web", "mobile", "chrome extension",
                 "browser", "automation", "no-code", "low-code", "chatbot", "ai tool"]

    hard_count = sum(1 for t in hard_tech if t in all_text)
    easy_count = sum(1 for t in easy_tech if t in all_text)

    if hard_count == 0 and easy_count >= 1:
        return min(100, 80 + easy_count * 5)
    elif hard_count <= 1 and easy_count >= 1:
        return min(79, 60 + easy_count * 5)
    elif hard_count <= 1:
        return min(59, 40 + 10)
    else:
        return max(0, 39 - (hard_count - 1) * 10)


def compute_timing(event: dict) -> int:
    """Compute timing score (0-100).

    Scoring rules (PRD Section 7.3):
    - 80-100: First signal within last 7 days, signal_count growing week-over-week
    - 60-79: Signals within last 30 days, stable or growing
    - 40-59: Signals in last 30-90 days, stable
    - 0-39: Signals older than 90 days, or market already saturated
    """
    first_seen = event.get("first_seen_at", "")
    signal_count = event.get("signal_count", 1)

    # Parse first_seen_at
    if first_seen:
        try:
            if isinstance(first_seen, str):
                first_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
            else:
                first_dt = first_seen
        except Exception:
            first_dt = None
    else:
        first_dt = None

    now = datetime.now(timezone.utc)

    if first_dt:
        age_days = (now - first_dt).days
    else:
        age_days = 30  # Assume moderate age if unknown

    # Growing signal
    growing = signal_count >= 3

    if age_days <= 7 and growing:
        return min(100, 80 + signal_count * 3)
    elif age_days <= 7:
        return min(89, 80 + signal_count * 2)
    elif age_days <= 30 and growing:
        return min(79, 60 + signal_count * 3)
    elif age_days <= 30:
        return min(69, 60 + signal_count)
    elif age_days <= 90:
        return min(59, 40 + (90 - age_days) // 10)
    else:
        return max(0, 39 - (age_days - 90) // 30 * 10)


def classify_opportunity_type(event: dict, score_breakdown: dict) -> str:
    """Classify opportunity type based on event signals.

    Returns one of: fast_follow, innovation, infrastructure, meta_tool
    """
    keywords = event.get("keywords", []) or []
    categories = event.get("categories", []) or []
    description = (event.get("description", "") or "").lower()
    event_type = event.get("event_type", "")

    all_text = " ".join(keywords + categories).lower() + " " + description

    # Developer/tools signals → infrastructure or meta_tool
    if any(t in all_text for t in ["developer", "dev tool", "api", "sdk", "library", "framework", "cli"]):
        if any(t in all_text for t in ["ai", "llm", "assistant", "automation", "test", "coding"]):
            return "meta_tool"
        return "infrastructure"

    # AI-native new solution → innovation
    if any(t in all_text for t in ["ai", "llm", "gpt", "chatbot", "generative", "agent"]):
        if any(t in all_text for t in ["new", "launch", "first", "novel"]):
            return "innovation"
        return "fast_follow"

    # Fast follow: copy for new market/audience
    if any(t in all_text for t in ["clone", "like", "competitor", "alternative", "vs ", "instead of"]):
        return "fast_follow"

    # Funding + launch signals → fast_follow
    if event_type in ("funding_round", "startup_launch"):
        return "fast_follow"

    # Default: fast_follow (copy proven concept)
    return "fast_follow"


def classify_imitation_difficulty(event: dict, opp_type: str, score_breakdown: dict) -> str:
    """Classify imitation difficulty.

    Returns: easy, medium, hard

    Rules (PRD Section 7.3):
    - easy: No proprietary data, no network effects, simple tech stack
    - medium: Some data moat or integration complexity
    - hard: Strong network effects, complex tech, regulatory hurdles
    """
    keywords = event.get("keywords", []) or []
    categories = event.get("categories", []) or []
    description = (event.get("description", "") or "").lower()

    all_text = " ".join(keywords + categories).lower() + " " + description

    # Hard indicators (checked first, before medium)
    if any(i in all_text for i in ["blockchain", "crypto"]):
        return "hard"
    if any(i in all_text for i in ["network effect", "data moat", "proprietary data", "regulated", "compliance",
                                     "hipaa", "soc2", "enterprise", "security critical",
                                     "real-time", "streaming"]):
        return "hard"
    if any(i in all_text for i in ["ml", "machine learning", "deep learning", "nlp", "computer vision"]):
        return "hard"

    # Medium indicators (integration complexity)
    medium_indicators = [
        "integration", "api", "sdk", "third-party", "payments", "stripe",
        "complex", "multi-step"
    ]
    medium_count = sum(1 for i in medium_indicators if i in all_text)
    if medium_count >= 2:
        return "medium"

    return "easy"


def score_to_label(score: int) -> str:
    """Convert numeric score to label.

    | Score Range | Label |
    | 80-100 | Very High |
    | 70-79 | High |
    | 55-69 | Medium |
    | 40-54 | Low |
    | 0-39 | Ignore |
    """
    if score >= 80:
        return "very_high"
    elif score >= 70:
        return "high"
    elif score >= 55:
        return "medium"
    elif score >= 40:
        return "low"
    else:
        return "ignore"
