"""Tests for TrendRadar analyzer."""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.trends import (
    analyze_daily_trends,
    generate_trend_summary,
    _heuristic_analysis,
    _extract_signals,
)
from analyzer.digest import (
    generate_daily_digest,
    generate_weekly_digest,
    format_for_slack,
    format_for_email,
)


class TestTrendAnalysis:
    """Tests for trend analysis."""

    def test_analyze_daily_trends_returns_dict(self):
        """Test that analysis returns a dict."""
        all_data = {
            "ycombinator": [
                {"name": "AI Startup", "industry": "AI/ML"},
                {"name": "Dev Tool", "industry": "Developer Tools"},
            ],
            "producthunt": [
                {"name": "AI Product", "tagline": "AI tool", "votes": 100},
            ],
        }
        result = analyze_daily_trends(all_data)
        assert isinstance(result, dict)
        assert "hot_categories" in result
        assert "recommendations" in result

    def test_heuristic_analysis(self):
        """Test heuristic analysis fallback."""
        all_data = {
            "hackernews": [
                {"title": "New AI library", "score": 100},
            ],
            "vc_funding": [
                {"company": "AI Startup", "sector": "AI/ML", "amount": 10000000},
            ],
        }
        result = _heuristic_analysis(all_data)
        assert "hot_categories" in result
        assert isinstance(result["hot_categories"], list)

    def test_extract_signals(self):
        """Test signal extraction from items."""
        items = [
            {"name": "AI Startup", "description": "AI-powered tool"},
            {"name": "Fintech App", "description": "Payment processing"},
        ]
        signals = _extract_signals(items)
        assert "categories" in signals
        assert isinstance(signals["categories"], list)

    def test_generate_trend_summary(self):
        """Test trend summary generation."""
        trends = {
            "hot_categories": ["AI/ML", "SaaS"],
            "emerging_patterns": ["LLM applications"],
            "vc_signals": ["AI getting big funding"],
            "recommendations": ["Focus on vertical AI"],
        }
        summary = generate_trend_summary(trends)
        assert isinstance(summary, str)
        assert "TrendRadar" in summary
        assert "AI/ML" in summary


class TestDigest:
    """Tests for digest generation."""

    @patch("analyzer.digest.yc.fetch_latest_batch")
    @patch("analyzer.digest.producthunt.fetch_today_trending")
    @patch("analyzer.digest.hackernews.fetch_top_stories")
    @patch("analyzer.digest.vc_funding.fetch_recent_funding")
    def test_generate_daily_digest(self, mock_vc, mock_hn, mock_ph, mock_yc):
        """Test daily digest generation."""
        mock_yc.return_value = [{"name": "YC Company"}]
        mock_ph.return_value = [{"name": "PH Product"}]
        mock_hn.return_value = [{"title": "HN Story"}]
        mock_vc.return_value = [{"company": "VC Company"}]

        result = generate_daily_digest()
        assert isinstance(result, dict)
        assert "date" in result
        assert "hot_categories" in result
        assert "sources_count" in result

    @patch("analyzer.digest.yc.fetch_all_batches_since")
    @patch("analyzer.digest.producthunt.fetch_weekly_top")
    @patch("analyzer.digest.hackernews.fetch_top_stories")
    @patch("analyzer.digest.vc_funding.fetch_recent_funding")
    def test_generate_weekly_digest(self, mock_vc, mock_hn, mock_ph, mock_yc):
        """Test weekly digest generation."""
        mock_yc.return_value = []
        mock_ph.return_value = []
        mock_hn.return_value = []
        mock_vc.return_value = []

        result = generate_weekly_digest()
        assert isinstance(result, dict)
        assert "type" in result
        assert result["type"] == "weekly"

    def test_format_for_slack(self):
        """Test Slack formatting."""
        digest = {
            "date": "2024-01-01",
            "sources_count": 4,
            "generated_at": "2024-01-01T12:00:00",
            "hot_categories": ["AI/ML"],
            "emerging_patterns": ["LLM apps"],
            "recommendations": ["Build in AI"],
        }
        result = format_for_slack(digest)
        assert "blocks" in result
        assert isinstance(result["blocks"], list)

    def test_format_for_email(self):
        """Test email formatting."""
        digest = {
            "date": "2024-01-01",
            "sources_count": 4,
            "generated_at": "2024-01-01T12:00:00",
            "hot_categories": ["AI/ML"],
            "emerging_patterns": ["LLM apps"],
            "recommendations": ["Build in AI"],
        }
        result = format_for_email(digest)
        assert isinstance(result, str)
        assert "<html>" in result
        assert "TrendRadar" in result


class TestStorage:
    """Tests for storage module."""

    def test_save_and_load_snapshot(self):
        """Test saving and retrieving snapshots."""
        from storage.trends import save_snapshot, get_latest, get_all_latest
        
        # Save a test snapshot
        snapshot = save_snapshot("test_source", {"items": ["test1", "test2"]})
        assert snapshot["source"] == "test_source"
        assert "timestamp" in snapshot
        
        # Retrieve it
        latest = get_latest("test_source")
        assert latest is not None
        assert latest["source"] == "test_source"
        
        # Check all latest
        all_latest = get_all_latest()
        assert "test_source" in all_latest
