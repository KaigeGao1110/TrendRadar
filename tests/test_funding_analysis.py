"""Unit tests for Funding Analysis Engine."""

import os
import csv
import tempfile
import pytest

# Add project root to path
import sys
sys.path.insert(0, os.path.expanduser("~/Projects/TrendRadar"))

from analyzer.funding.parser import parse_amount, parse_valuation, parse_categories, load_funding_csv
from analyzer.funding.category_heatmap import generate_heatmap
from analyzer.funding.big_rounds import get_big_rounds
from analyzer.funding.competitor_watch import watch_competitors
from analyzer.funding.emerging_trends import detect_emerging
from analyzer.funding.pricing_anchor import calculate_pricing_anchors
from analyzer.funding.trend_comparison import compare_trends
from analyzer.funding.anomaly_detection import detect_anomalies


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CSV_DATA = [
    {
        "source": "fundbat",
        "title": "Jump ($105M / -)",
        "funding_amount": "$105M",
        "valuation": "-",
        "category": "Artificial Intelligence  Fintech  +1",
        "investors": "",
        "url": "https://fundbat.com/company/jump",
        "first_seen_at": "2026-04-24T21:45:46.204788+00:00",
    },
    {
        "source": "fundbat",
        "title": "GrubMarket ($858M / $4.5B)",
        "funding_amount": "$858M",
        "valuation": "$4.5B",
        "category": "E-Commerce  Artificial Intelligence",
        "investors": "",
        "url": "https://fundbat.com/company/grubmarket",
        "first_seen_at": "2026-04-24T21:45:28.323901+00:00",
    },
    {
        "source": "fundbat",
        "title": "Bird ($1.1B / $3.8B)",
        "funding_amount": "$1.1B",
        "valuation": "$3.8B",
        "category": "SaaS  Developer Tools  +2",
        "investors": "",
        "url": "https://fundbat.com/company/bird",
        "first_seen_at": "2026-04-20T10:00:00.000000+00:00",
    },
    {
        "source": "fundbat",
        "title": "Nscale ($3.7B / $14.6B)",
        "funding_amount": "$3.7B",
        "valuation": "$14.6B",
        "category": "Artificial Intelligence  Cloud Computing",
        "investors": "",
        "url": "https://fundbat.com/company/nscale",
        "first_seen_at": "2026-04-22T15:00:00.000000+00:00",
    },
    {
        "source": "fundbat",
        "title": "SmallCo ($5M / -)",
        "funding_amount": "$5M",
        "valuation": "-",
        "category": "SaaS",
        "investors": "",
        "url": "https://fundbat.com/company/smallco",
        "first_seen_at": "2026-04-15T12:00:00.000000+00:00",
    },
    {
        "source": "fundbat",
        "title": "Momentus ($34M / NASDAQ: MNTS)",
        "funding_amount": "$34M",
        "valuation": "NASDAQ: MNTS",
        "category": "Aerospace  Transportation",
        "investors": "",
        "url": "https://fundbat.com/company/momentus",
        "first_seen_at": "2026-04-24T21:45:54.265968+00:00",
    },
]


@pytest.fixture
def sample_csv(tmp_path):
    """Create a temporary CSV file with sample data."""
    csv_path = tmp_path / "funding_test.csv"
    fieldnames = ["source", "title", "funding_amount", "valuation", "category", "investors", "url", "first_seen_at"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(SAMPLE_CSV_DATA)
    return str(csv_path)


# ---------------------------------------------------------------------------
# Amount Parsing Tests
# ---------------------------------------------------------------------------

class TestParseAmount:
    def test_millions(self):
        assert parse_amount("$105M") == 105.0

    def test_billions(self):
        assert parse_amount("$4.5B") == 4500.0

    def test_billion_decimal(self):
        assert parse_amount("$1.1B") == 1100.0

    def test_large_billion(self):
        assert parse_amount("$3.7B") == 3700.0

    def test_dash(self):
        assert parse_amount("-") == 0.0

    def test_empty(self):
        assert parse_amount("") == 0.0

    def test_no_dollar_sign(self):
        assert parse_amount("105M") == 105.0

    def test_thousands(self):
        assert parse_amount("$500K") == 0.5


class TestParseValuation:
    def test_billions(self):
        assert parse_valuation("$4.5B") == 4500.0

    def test_millions(self):
        assert parse_valuation("$467M") == 467.0

    def test_ticker_symbol(self):
        assert parse_valuation("NASDAQ: MNTS") == 0.0

    def test_nyse_ticker(self):
        assert parse_valuation("NYSE: BOX") == 0.0

    def test_dash(self):
        assert parse_valuation("-") == 0.0


# ---------------------------------------------------------------------------
# Category Parsing Tests
# ---------------------------------------------------------------------------

class TestParseCategories:
    def test_double_space_separated(self):
        result = parse_categories("Artificial Intelligence  Fintech  +1")
        assert result == ["Artificial Intelligence", "Fintech"]

    def test_single_category(self):
        result = parse_categories("SaaS")
        assert result == ["SaaS"]

    def test_noise_labels_filtered(self):
        result = parse_categories("SaaS  Developer Tools  +2")
        assert result == ["SaaS", "Developer Tools"]

    def test_empty(self):
        result = parse_categories("")
        assert result == []

    def test_only_noise(self):
        result = parse_categories("+1  +2")
        assert result == []


# ---------------------------------------------------------------------------
# Category Heatmap Tests
# ---------------------------------------------------------------------------

class TestHeatmap:
    def test_generates_heatmap(self, sample_csv):
        result = generate_heatmap(sample_csv)
        assert "heatmap" in result
        assert "generated_at" in result
        assert len(result["heatmap"]) > 0

    def test_ai_top_category(self, sample_csv):
        result = generate_heatmap(sample_csv)
        # AI appears 3 times (Jump, GrubMarket, Nscale)
        ai_entry = next((h for h in result["heatmap"] if h["category"] == "Artificial Intelligence"), None)
        assert ai_entry is not None
        assert ai_entry["count"] == 3

    def test_heat_score_range(self, sample_csv):
        result = generate_heatmap(sample_csv)
        for item in result["heatmap"]:
            assert 0 <= item["heat_score"] <= 100

    def test_sorted_by_heat_score(self, sample_csv):
        result = generate_heatmap(sample_csv)
        scores = [h["heat_score"] for h in result["heatmap"]]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Big Rounds Tests
# ---------------------------------------------------------------------------

class TestBigRounds:
    def test_default_threshold(self, sample_csv):
        result = get_big_rounds(sample_csv)
        assert result["threshold_m"] == 50.0
        # Should include: GrubMarket(858), Bird(1100), Nscale(3700), Jump(105)
        # Should exclude: SmallCo(5), Momentus(34)
        assert result["total"] == 4

    def test_custom_threshold(self, sample_csv):
        result = get_big_rounds(sample_csv, threshold_m=200.0)
        # Should include: GrubMarket(858), Bird(1100), Nscale(3700)
        assert result["total"] == 3

    def test_sorted_by_amount(self, sample_csv):
        result = get_big_rounds(sample_csv)
        amounts = [r["amount_m"] for r in result["big_rounds"]]
        assert amounts == sorted(amounts, reverse=True)

    def test_company_name_extraction(self, sample_csv):
        result = get_big_rounds(sample_csv)
        companies = [r["company"] for r in result["big_rounds"]]
        assert "GrubMarket" in companies
        assert "Jump" in companies

    def test_valuation_parsing(self, sample_csv):
        result = get_big_rounds(sample_csv)
        grubmarket = next(r for r in result["big_rounds"] if r["company"] == "GrubMarket")
        assert grubmarket["valuation_b"] == 4.5

    def test_ticker_valuation_excluded(self, sample_csv):
        result = get_big_rounds(sample_csv, threshold_m=30.0)
        momentus = next((r for r in result["big_rounds"] if r["company"] == "Momentus"), None)
        if momentus:
            assert momentus["valuation_b"] is None


# ---------------------------------------------------------------------------
# Competitor Watch Tests
# ---------------------------------------------------------------------------

class TestCompetitorWatch:
    def test_keyword_match(self, sample_csv):
        result = watch_competitors(sample_csv, ["AI"])
        assert result["total_matches"] > 0

    def test_empty_keywords(self, sample_csv):
        result = watch_competitors(sample_csv, [])
        assert result["total_matches"] == 0

    def test_case_insensitive(self, sample_csv):
        result = watch_competitors(sample_csv, ["artificial intelligence"])
        assert result["total_matches"] > 0

    def test_sorted_by_amount(self, sample_csv):
        result = watch_competitors(sample_csv, ["AI"])
        amounts = [m["amount_m"] for m in result["matches"] if m["amount_m"] is not None]
        assert amounts == sorted(amounts, reverse=True)


# ---------------------------------------------------------------------------
# Emerging Trends Tests
# ---------------------------------------------------------------------------

class TestEmergingTrends:
    def test_detects_emerging(self, sample_csv):
        result = detect_emerging(sample_csv)
        assert "emerging" in result
        assert len(result["emerging"]) > 0

    def test_growth_rate_calculated(self, sample_csv):
        result = detect_emerging(sample_csv)
        for e in result["emerging"]:
            assert "growth_rate" in e
            assert "this_week" in e
            assert "baseline_avg" in e


# ---------------------------------------------------------------------------
# Pricing Anchor Tests
# ---------------------------------------------------------------------------

class TestPricingAnchor:
    def test_calculates_anchors(self, sample_csv):
        result = calculate_pricing_anchors(sample_csv)
        assert "anchors" in result
        assert len(result["anchors"]) > 0

    def test_statistics_fields(self, sample_csv):
        result = calculate_pricing_anchors(sample_csv)
        for cat, stats in result["anchors"].items():
            assert "count" in stats
            assert "min_m" in stats
            assert "max_m" in stats
            assert "avg_m" in stats
            assert "median_m" in stats
            assert "p25_m" in stats
            assert "p75_m" in stats


# ---------------------------------------------------------------------------
# Trend Comparison Tests
# ---------------------------------------------------------------------------

class TestTrendComparison:
    def test_compare_two_heatmaps(self):
        current = {
            "heatmap": [
                {"category": "AI", "heat_score": 90.0},
                {"category": "SaaS", "heat_score": 60.0},
                {"category": "Crypto", "heat_score": 20.0},
            ]
        }
        previous = {
            "heatmap": [
                {"category": "AI", "heat_score": 70.0},
                {"category": "SaaS", "heat_score": 55.0},
                {"category": "Crypto", "heat_score": 50.0},
            ]
        }
        result = compare_trends(current, previous)
        assert len(result["warming"]) > 0
        assert len(result["cooling"]) > 0
        # AI warmed up (90 vs 70 = +28.6%)
        ai_warming = any(w["category"] == "AI" for w in result["warming"])
        assert ai_warming
        # Crypto cooled down (20 vs 50 = -60%)
        crypto_cooling = any(c["category"] == "Crypto" for c in result["cooling"])
        assert crypto_cooling

    def test_stable_categories(self):
        current = {"heatmap": [{"category": "SaaS", "heat_score": 55.0}]}
        previous = {"heatmap": [{"category": "SaaS", "heat_score": 55.0}]}
        result = compare_trends(current, previous)
        assert len(result["stable"]) == 1


# ---------------------------------------------------------------------------
# Anomaly Detection Tests
# ---------------------------------------------------------------------------

class TestAnomalyDetection:
    def test_runs_without_error(self, sample_csv):
        result = detect_anomalies(sample_csv)
        assert "anomalies" in result
        assert "sigma_threshold" in result

    def test_sigma_threshold(self, sample_csv):
        result = detect_anomalies(sample_csv)
        assert result["sigma_threshold"] == 2.0


# ---------------------------------------------------------------------------
# Integration: Run with real data (if available)
# ---------------------------------------------------------------------------

class TestWithRealData:
    """Tests using the actual funding.csv if available."""

    REAL_CSV = os.path.expanduser("~/Projects/TrendRadar/output/funding.csv")

    @pytest.mark.skipif(
        not os.path.exists(REAL_CSV),
        reason="Real funding.csv not available"
    )
    def test_heatmap_with_real_data(self):
        result = generate_heatmap(self.REAL_CSV)
        assert len(result["heatmap"]) > 0
        # AI should be near the top
        top_cats = [h["category"] for h in result["heatmap"][:5]]
        assert any("AI" in cat or "Artificial" in cat for cat in top_cats)

    @pytest.mark.skipif(
        not os.path.exists(REAL_CSV),
        reason="Real funding.csv not available"
    )
    def test_big_rounds_with_real_data(self):
        result = get_big_rounds(self.REAL_CSV)
        assert result["total"] > 0
        # All amounts should be >= threshold
        for r in result["big_rounds"]:
            assert r["amount_m"] >= 50.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])