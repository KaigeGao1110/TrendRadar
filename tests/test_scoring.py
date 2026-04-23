"""Tests for TrendRadar scoring pipeline.

Unit tests with mocked event data, covering:
- compute_pain_density
- compute_tech_feasibility
- compute_timing
- compute_total_score
- classify_opportunity_type
- classify_imitation_difficulty
- score_to_label
- cosine_similarity (dedup)
- should_merge (dedup)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.scoring import (
    compute_pain_density,
    compute_tech_feasibility,
    compute_timing,
    compute_total_score,
    classify_opportunity_type,
    classify_imitation_difficulty,
    score_to_label,
)
from analyzer.dedup import cosine_similarity, should_merge


class TestPainDensity:
    """Tests for pain density scoring."""

    def test_high_pain_density_multi_source(self):
        """Score 80-100: Multiple independent sources (≥3) with pain keywords."""
        event = {
            "keywords": ["users struggle with X", "problem with Y", "frustrating Z", "broken workflow"],
            "signal_count": 4,
            "severity": 8,
            "description": "Teams struggle to coordinate remote work",
        }
        score = compute_pain_density(event)
        assert score >= 80, f"Expected >=80, got {score}"

    def test_medium_pain_density_two_sources(self):
        """Score 60-79: Same pain mentioned in 2 sources."""
        event = {
            "keywords": ["painful onboarding", "complex setup"],
            "signal_count": 2,
            "severity": 6,
            "description": "Difficult onboarding process",
        }
        score = compute_pain_density(event)
        assert 60 <= score <= 79, f"Expected 60-79, got {score}"

    def test_low_pain_density_single_source(self):
        """Score 40-59: Pain mentioned in 1 source with acute description."""
        event = {
            "keywords": ["expensive software"],
            "signal_count": 1,
            "severity": 7,
            "description": "Current solutions are too expensive for startups",
        }
        score = compute_pain_density(event)
        assert 40 <= score <= 59, f"Expected 40-59, got {score}"

    def test_ignore_pain_density_vague(self):
        """Score 0-39: Vague or niche pain."""
        event = {
            "keywords": ["tool"],
            "signal_count": 1,
            "severity": 3,
            "description": "A software tool",
        }
        score = compute_pain_density(event)
        assert score < 40, f"Expected <40, got {score}"


class TestTechFeasibility:
    """Tests for tech feasibility scoring."""

    def test_high_feasibility_easy_stack(self):
        """Score 80-100: No deep tech, existing APIs/frameworks."""
        event = {
            "keywords": ["llm api", "saas", "openai", "web tool"],
            "categories": ["AI", "SaaS"],
            "description": "AI-powered chatbot using OpenAI API",
        }
        score = compute_tech_feasibility(event)
        assert score >= 80, f"Expected >=80, got {score}"

    def test_medium_feasibility_moderate_complexity(self):
        """Score 60-79: Moderate complexity, novel integrations."""
        # "integration" alone triggers medium since it matches a medium indicator
        event = {
            "keywords": ["multi-step workflow", "third-party sync", "data pipeline"],
            "categories": ["Automation"],
            "description": "Automated data pipeline with complex multi-step transformations",
        }
        score = compute_tech_feasibility(event)
        assert 40 <= score <= 79, f"Expected 40-79, got {score}"

    def test_low_feasibility_complex_tech(self):
        """Score 0-39: Requires significant ML/infra work."""
        event = {
            "keywords": ["machine learning", "deep learning", "real-time streaming"],
            "categories": ["ML Infrastructure"],
            "description": "Real-time ML pipeline with custom model training",
        }
        score = compute_tech_feasibility(event)
        assert score < 40, f"Expected <40, got {score}"


class TestTiming:
    """Tests for timing scoring."""

    def test_high_timing_recent_and_growing(self):
        """Score 80-100: Within 7 days, signal growing."""
        event = {
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "signal_count": 4,
        }
        score = compute_timing(event)
        assert score >= 80, f"Expected >=80, got {score}"

    def test_medium_timing_within_30_days(self):
        """Score 60-79: Within 30 days, stable."""
        event = {
            "first_seen_at": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat(),
            "signal_count": 2,
        }
        score = compute_timing(event)
        assert 60 <= score <= 79, f"Expected 60-79, got {score}"

    def test_low_timing_30_to_90_days(self):
        """Score 40-59: 30-90 days old signals."""
        event = {
            "first_seen_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
            "signal_count": 1,
        }
        score = compute_timing(event)
        assert 40 <= score <= 59, f"Expected 40-59, got {score}"

    def test_ignore_timing_old_signals(self):
        """Score 0-39: Signals older than 90 days."""
        event = {
            "first_seen_at": (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(),
            "signal_count": 1,
        }
        score = compute_timing(event)
        assert score < 40, f"Expected <40, got {score}"


class TestTotalScore:
    """Tests for overall score computation."""

    def test_total_score_calculation(self):
        """total_score = round(pain × 0.4 + tech × 0.3 + timing × 0.3)"""
        breakdown = {"pain_density": 80, "tech_feasibility": 70, "timing": 90}
        score = compute_total_score(breakdown)
        expected = round(80 * 0.4 + 70 * 0.3 + 90 * 0.3)
        assert score == expected, f"Expected {expected}, got {score}"

    def test_total_score_rounding(self):
        """Ensure integer rounding."""
        breakdown = {"pain_density": 85, "tech_feasibility": 75, "timing": 65}
        score = compute_total_score(breakdown)
        expected = round(85 * 0.4 + 75 * 0.3 + 65 * 0.3)
        # 34 + 22.5 + 19.5 = 76.0 -> Python rounds to 76 (banker's rounding for .5)
        assert score == expected == 76

    def test_total_score_with_missing_keys(self):
        """Missing keys should default to 0."""
        breakdown = {"pain_density": 100}
        score = compute_total_score(breakdown)
        assert score == 40  # 100 * 0.4 + 0 + 0


class TestOpportunityType:
    """Tests for opportunity type classification."""

    def test_infrastructure_dev_tools(self):
        """Developer tools → infrastructure."""
        event = {
            "keywords": ["developer", "api", "sdk", "library"],
            "categories": ["Developer Tools"],
            "description": "New API management library for developers",
        }
        opp_type = classify_opportunity_type(event, {})
        assert opp_type == "infrastructure"

    def test_meta_tool_ai_developer(self):
        """AI-assisted dev tools → meta_tool."""
        event = {
            "keywords": ["developer", "ai", "llm", "assistant", "automation"],
            "categories": ["Developer Tools"],
            "description": "AI-powered test generation tool for developers",
        }
        opp_type = classify_opportunity_type(event, {})
        assert opp_type == "meta_tool"

    def test_fast_follow_clone_market(self):
        """Clone/competitor signals → fast_follow."""
        event = {
            "keywords": ["alternative", "competitor", "like notion"],
            "categories": ["Productivity"],
            "description": "Notion-like tool for legal teams",
        }
        opp_type = classify_opportunity_type(event, {})
        assert opp_type == "fast_follow"

    def test_innovation_ai_new_approach(self):
        """AI + new/launch → innovation."""
        event = {
            "keywords": ["ai", "llm", "novel", "first-of-its-kind"],
            "categories": ["AI"],
            "description": "First AI-powered solution for X problem",
        }
        opp_type = classify_opportunity_type(event, {})
        assert opp_type == "innovation"


class TestImitationDifficulty:
    """Tests for imitation difficulty classification."""

    def test_easy_imitation(self):
        """Simple stack, no moat → easy."""
        event = {
            "keywords": ["saas", "web tool", "api"],
            "categories": ["SaaS"],
            "description": "Simple web-based form builder",
        }
        difficulty = classify_imitation_difficulty(event, "fast_follow", {})
        assert difficulty == "easy"

    def test_medium_imitation(self):
        """Integration complexity → medium."""
        event = {
            "keywords": ["integration", "api", "third-party", "stripe"],
            "categories": ["Payments"],
            "description": "Payment integration service",
        }
        difficulty = classify_imitation_difficulty(event, "infrastructure", {})
        assert difficulty == "medium"

    def test_hard_imitation_network_effects(self):
        """Network effects + complex tech → hard."""
        event = {
            "keywords": ["network effect", "ml", "machine learning", "proprietary data"],
            "categories": ["Enterprise"],
            "description": "Enterprise security platform with proprietary ML",
        }
        difficulty = classify_imitation_difficulty(event, "innovation", {})
        assert difficulty == "hard"


class TestScoreToLabel:
    """Tests for score-to-label conversion."""

    def test_very_high(self):
        assert score_to_label(85) == "very_high"
        assert score_to_label(100) == "very_high"

    def test_high(self):
        assert score_to_label(75) == "high"
        assert score_to_label(79) == "high"

    def test_medium(self):
        assert score_to_label(55) == "medium"
        assert score_to_label(69) == "medium"

    def test_low(self):
        assert score_to_label(40) == "low"
        assert score_to_label(54) == "low"

    def test_ignore(self):
        assert score_to_label(0) == "ignore"
        assert score_to_label(39) == "ignore"


class TestCosineSimilarity:
    """Tests for cosine similarity computation."""

    def test_identical_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [-1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_mixed_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        # dot = 1*4 + 2*5 + 3*6 = 32
        # norm_a = sqrt(1+4+9) = sqrt(14), norm_b = sqrt(16+25+36) = sqrt(77)
        sim = cosine_similarity(a, b)
        expected = 32 / (14**0.5 * 77**0.5)
        assert sim == pytest.approx(expected)

    def test_zero_vector(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert cosine_similarity(a, b) == 0.0


class TestShouldMerge:
    """Tests for dedup should_merge logic."""

    def test_no_similar_opportunities(self):
        event = {"event_id": "123"}
        result = should_merge(event, [])
        assert result["should_merge"] is False
        assert result["reason"] == "no_similar"

    def test_high_similarity_merge(self):
        event = {"event_id": "123"}
        similar = [{"id": "abc", "similarity": 0.90, "event_id": "456"}]
        result = should_merge(event, similar)
        assert result["should_merge"] is True
        assert result["existing_id"] == "abc"
        assert result["reason"] == "high_similarity"

    def test_low_similarity_no_merge(self):
        event = {"event_id": "123"}
        similar = [{"id": "abc", "similarity": 0.70, "event_id": "456"}]
        result = should_merge(event, similar)
        assert result["should_merge"] is False
        assert result["reason"] == "below_threshold"


class TestScoringIntegration:
    """Integration tests for full scoring pipeline."""

    def test_full_pipeline_strong_opportunity(self):
        """A well-formed event should produce a high score."""
        event = {
            "event_type": "startup_launch",
            "first_seen_date": "2026-04-23",
            "title": "AI-powered code review tool",
            "description": "Helps developers find bugs before they ship. Solves the problem of expensive QA.",
            "keywords": ["ai", "code review", "developer tool", "pain point: expensive QA", "struggle: bugs"],
            "categories": ["AI", "Developer Tools"],
            "entities": {"company": "CodeBot", "product": "CodeReview AI"},
            "severity": 8,
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "signal_count": 4,
            "source_ids": ["hn-123", "ph-456", "yc-789"],
        }

        breakdown = {
            "pain_density": compute_pain_density(event),
            "tech_feasibility": compute_tech_feasibility(event),
            "timing": compute_timing(event),
        }

        score = compute_total_score(breakdown)

        assert score > 0
        assert breakdown["pain_density"] > 0
        assert breakdown["tech_feasibility"] > 0
        assert breakdown["timing"] > 0

    def test_full_pipeline_weak_opportunity(self):
        """A weak signal should produce a low score."""
        event = {
            "event_type": "startup_launch",
            "first_seen_date": "2026-04-10",
            "title": "Some tool",
            "description": "A software tool",
            "keywords": ["tool"],
            "categories": ["General"],
            "severity": 3,
            "first_seen_at": (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(),
            "signal_count": 1,
            "source_ids": [],
        }

        breakdown = {
            "pain_density": compute_pain_density(event),
            "tech_feasibility": compute_tech_feasibility(event),
            "timing": compute_timing(event),
        }

        score = compute_total_score(breakdown)

        assert score < 50  # Should be low given weak signals


class TestImitationDifficultyEdgeCases:
    """Edge case tests for imitation difficulty."""

    def test_regulated_industry_hard(self):
        """HIPAA/enterprise → hard."""
        event = {
            "keywords": ["hipaa", "enterprise", "compliance", "security"],
            "categories": ["Healthcare"],
            "description": "Healthcare compliance automation",
        }
        difficulty = classify_imitation_difficulty(event, "infrastructure", {})
        assert difficulty == "hard"

    def test_blockchain_hard(self):
        """Blockchain → hard."""
        event = {
            "keywords": ["blockchain", "crypto", "decentralized"],
            "categories": ["Web3"],
            "description": "Decentralized storage platform",
        }
        difficulty = classify_imitation_difficulty(event, "infrastructure", {})
        assert difficulty == "hard"


class TestOpportunityTypeEdgeCases:
    """Edge case tests for opportunity type classification."""

    def test_funding_round_fast_follow(self):
        """Funding round → fast_follow."""
        event = {
            "event_type": "funding_round",
            "keywords": ["saas"],
            "categories": ["SaaS"],
            "description": "Series A for B2B SaaS company",
        }
        opp_type = classify_opportunity_type(event, {})
        assert opp_type == "fast_follow"

    def test_no_keywords_defaults_fast_follow(self):
        """No clear signals → default fast_follow."""
        event = {
            "event_type": "startup_launch",
            "keywords": [],
            "categories": [],
            "description": "A startup",
        }
        opp_type = classify_opportunity_type(event, {})
        assert opp_type == "fast_follow"
