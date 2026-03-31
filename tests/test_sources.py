"""Tests for TrendRadar source fetchers."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import yc, producthunt, hackernews, vc_funding


class TestYCSources:
    """Tests for YC source."""

    def test_fetch_latest_batch_returns_list(self):
        """Test that fetch returns a list."""
        result = yc.fetch_latest_batch()
        assert isinstance(result, list)

    def test_fetch_latest_batch_has_required_fields(self):
        """Test that each company has required fields."""
        result = yc.fetch_latest_batch()
        if result:
            for item in result:
                assert "name" in item
                assert "batch" in item
                assert "industry" in item

    def test_categorize_companies(self):
        """Test company categorization."""
        companies = [
            {"name": "AI Startup", "one_liner": "AI-powered tool", "batch": "W25"},
            {"name": "Fintech App", "one_liner": "Payment processing", "batch": "W25"},
            {"name": "Another AI", "one_liner": "Machine learning API", "batch": "W25"},
        ]
        categories = yc.categorize_companies(companies)
        assert isinstance(categories, dict)
        assert len(categories) > 0

    def test_fetch_all_batches_since(self):
        """Test fetching multiple batches."""
        result = yc.fetch_all_batches_since(year=2024)
        assert isinstance(result, list)


class TestProductHunt:
    """Tests for Product Hunt source."""

    def test_fetch_today_trending_returns_list(self):
        """Test that fetch returns a list."""
        result = producthunt.fetch_today_trending()
        assert isinstance(result, list)

    def test_fetch_today_trending_has_required_fields(self):
        """Test that each product has required fields."""
        result = producthunt.fetch_today_trending()
        if result:
            for item in result:
                assert "name" in item
                assert "tagline" in item
                assert "votes" in item

    def test_categorize_products(self):
        """Test product categorization."""
        products = [
            {"name": "AI Tool", "tagline": "AI-powered design", "votes": 100, "topics": ["AI"]},
            {"name": "Dev Tool", "tagline": "API management", "votes": 50, "topics": ["Developer Tools"]},
        ]
        categories = producthunt.categorize_products(products)
        assert isinstance(categories, dict)

    def test_infer_topics(self):
        """Test topic inference from tagline."""
        topics = producthunt._infer_topics("AI-powered chatbot for teams")
        assert "AI" in topics


class TestHackerNews:
    """Tests for Hacker News source."""

    def test_fetch_top_stories_returns_list(self):
        """Test that fetch returns a list."""
        result = hackernews.fetch_top_stories(limit=5)
        assert isinstance(result, list)

    def test_fetch_top_stories_has_required_fields(self):
        """Test that each story has required fields."""
        result = hackernews.fetch_top_stories(limit=5)
        if result:
            for item in result:
                assert "id" in item
                assert "title" in item
                assert "score" in item

    def test_detect_tech_trends(self):
        """Test tech trend detection."""
        stories = [
            {"title": "Show HN: I built an AI code reviewer", "score": 100},
            {"title": "New machine learning library released", "score": 80},
            {"title": "Ask HN: Best AI tools for startups?", "score": 50},
        ]
        trends = hackernews.detect_tech_trends(stories)
        assert isinstance(trends, list)

    def test_fetch_trending_keywords(self):
        """Test keyword extraction."""
        keywords = hackernews.fetch_trending_keywords(hours=24, limit=10)
        assert isinstance(keywords, list)
        if keywords:
            assert isinstance(keywords[0], tuple)
            assert len(keywords[0]) == 2


class TestVCFunding:
    """Tests for VC funding source."""

    def test_fetch_recent_funding_returns_list(self):
        """Test that fetch returns a list."""
        result = vc_funding.fetch_recent_funding()
        assert isinstance(result, list)

    def test_fetch_recent_funding_has_required_fields(self):
        """Test that each round has required fields."""
        result = vc_funding.fetch_recent_funding()
        if result:
            for item in result:
                assert "company" in item
                assert "amount" in item
                assert "round" in item

    def test_categorize_funding(self):
        """Test funding categorization."""
        funding = [
            {"company": "AI Startup", "amount": 10000000, "round": "Series A", "sector": "AI/ML"},
            {"company": "Fintech App", "amount": 5000000, "round": "Seed", "sector": "Fintech"},
        ]
        result = vc_funding.categorize_funding(funding)
        assert "by_sector" in result
        assert "by_round" in result

    def test_detect_funding_trends(self):
        """Test funding trend detection."""
        funding = [
            {"company": "AI Startup", "amount": 10000000, "round": "Series A", "sector": "AI/ML"},
            {"company": "AI Tool", "amount": 5000000, "round": "Seed", "sector": "AI/ML"},
        ]
        trends = vc_funding.detect_funding_trends(funding)
        assert isinstance(trends, list)

    def test_extract_amount(self):
        """Test amount extraction from text."""
        assert vc_funding._extract_amount("Company raises $5M seed") == 5000000
        assert vc_funding._extract_amount("Company raises $15M Series A") == 15000000
        assert vc_funding._extract_amount("Company raises $1.5M") == 1500000

    def test_extract_round(self):
        """Test round type extraction."""
        assert "Seed" in vc_funding._extract_round("Company raises $5M seed")
        assert "Series A" in vc_funding._extract_round("Company raises $15M Series A")
