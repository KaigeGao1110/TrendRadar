#!/usr/bin/env python3
"""Generate TrendRadar dashboard HTML from data sources."""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import chromadb
from dotenv import load_dotenv

# Load .env
load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_FILE = PROJECT_ROOT / "reports" / "dashboard.html"


def get_chroma_data():
    """Extract data from ChromaDB collections."""
    client = chromadb.PersistentClient(path=str(DATA_DIR / "chroma/"))

    # pain_signals collection
    pain_col = client.get_collection("pain_signals")
    pain_count = pain_col.count()
    pain_items = pain_col.get()

    pain_signals = {
        "total": pain_count,
        "by_source": {},
        "by_confidence_range": {"0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0},
        "cross_source_dist": {},
    }

    for meta in pain_items.get("metadatas", []):
        source = meta.get("source", "unknown")
        pain_signals["by_source"][source] = pain_signals["by_source"].get(source, 0) + 1

        conf = meta.get("confidence", 0)
        if conf < 0.2:
            pain_signals["by_confidence_range"]["0-0.2"] += 1
        elif conf < 0.4:
            pain_signals["by_confidence_range"]["0.2-0.4"] += 1
        elif conf < 0.6:
            pain_signals["by_confidence_range"]["0.4-0.6"] += 1
        elif conf < 0.8:
            pain_signals["by_confidence_range"]["0.6-0.8"] += 1
        else:
            pain_signals["by_confidence_range"]["0.8-1.0"] += 1

        cs_count = meta.get("cross_source_count", 0)
        pain_signals["cross_source_dist"][cs_count] = pain_signals["cross_source_dist"].get(cs_count, 0) + 1

    # opportunity_clusters collection
    opp_col = client.get_collection("opportunity_clusters")
    opp_count = opp_col.count()
    opp_items = opp_col.get()

    opportunities = {
        "total": opp_count,
        "score_histogram": [0] * 10,  # 0-0.1, 0.1-0.2, ..., 0.9-1.0
        "top_10": [],
        "by_source": {},
    }

    # Also get documents for titles
    opp_docs = opp_items.get("documents", [])

    scored_opps = []
    for i, meta in enumerate(opp_items.get("metadatas", [])):
        total_score = meta.get("total_score", 0)
        doc_id = opp_items["ids"][i]
        doc_title = opp_docs[i] if i < len(opp_docs) else doc_id
        # Truncate title at 60 chars
        if len(doc_title) > 60:
            doc_title = doc_title[:57] + "..."
        scored_opps.append({
            "id": doc_id,
            "title": doc_title,
            "total_score": round(total_score, 3),
            "pain_score": round(meta.get("pain_score", 0), 3),
            "timing_score": round(meta.get("timing_score", 0), 3),
            "cross_source_count": meta.get("cross_source_count", 0),
            "source": meta.get("source", "unknown"),
        })

        # histogram bucket
        bucket = min(int(total_score * 10), 9)
        opportunities["score_histogram"][bucket] += 1

        # by source
        source = meta.get("source", "unknown")
        opportunities["by_source"][source] = opportunities["by_source"].get(source, 0) + 1

    scored_opps.sort(key=lambda x: x["total_score"], reverse=True)
    opportunities["top_10"] = scored_opps[:10]

    return {"pain_signals": pain_signals, "opportunities": opportunities}


def get_sqlite_data():
    """Extract data from SQLite database."""
    conn = sqlite3.connect(str(DATA_DIR / "sec.db"))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # sec_form_d_filings
    cursor.execute("SELECT COUNT(*) as cnt FROM sec_form_d_filings")
    filings_count = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT industry_group,
               COUNT(*) as cnt,
               SUM(total_offering_amount) as total_amount
        FROM sec_form_d_filings
        GROUP BY industry_group
        ORDER BY cnt DESC
        LIMIT 10
    """)
    by_industry = [{"industry": row["industry_group"], "count": row["cnt"], "total_amount": row["total_amount"] or 0}
                   for row in cursor.fetchall()]

    # Amount ranges
    amount_ranges = [
        ("<1M", 0, 1_000_000),
        ("1-5M", 1_000_000, 5_000_000),
        ("5-20M", 5_000_000, 20_000_000),
        ("20-50M", 20_000_000, 50_000_000),
        ("50-100M", 50_000_000, 100_000_000),
        (">100M", 100_000_000, float("inf")),
    ]
    by_amount_range = []
    for label, lo, hi in amount_ranges:
        cursor.execute(
            "SELECT COUNT(*) FROM sec_form_d_filings WHERE total_offering_amount >= ? AND total_offering_amount < ?",
            (lo, hi)
        )
        by_amount_range.append({"range": label, "count": cursor.fetchone()[0]})

    # By date (last 30 days)
    cursor.execute("""
        SELECT filing_date, COUNT(*) as cnt
        FROM sec_form_d_filings
        WHERE filing_date >= date('now', '-30 days')
        GROUP BY filing_date
        ORDER BY filing_date
    """)
    by_date = [{"date": row["filing_date"], "count": row["cnt"]} for row in cursor.fetchall()]

    # Top 10 deals by amount (with industry_group)
    cursor.execute("""
        SELECT entity_name, total_offering_amount, filing_date, industry_group
        FROM sec_form_d_filings
        ORDER BY total_offering_amount DESC
        LIMIT 10
    """)
    top_deals = [
        {
            "rank": i + 1,
            "entity_name": row["entity_name"],
            "amount": row["total_offering_amount"],
            "industry_group": row["industry_group"] or "Unknown",
            "filing_date": row["filing_date"],
        }
        for i, row in enumerate(cursor.fetchall())
    ]

    # sec_company_profiles
    cursor.execute("SELECT COUNT(*) as cnt FROM sec_company_profiles")
    profiles_count = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT enrichment_quality, COUNT(*) as cnt
        FROM sec_company_profiles
        GROUP BY enrichment_quality
    """)
    enrichment_dist = [{"quality": row["enrichment_quality"], "count": row["cnt"]} for row in cursor.fetchall()]

    cursor.execute("""
        SELECT primary_sector, COUNT(*) as cnt
        FROM sec_company_profiles
        GROUP BY primary_sector
        ORDER BY cnt DESC
    """)
    sector_dist = [{"sector": row["primary_sector"], "count": row["cnt"]} for row in cursor.fetchall()]

    conn.close()

    return {
        "filings": {
            "total": filings_count,
            "by_industry": by_industry,
            "by_amount_range": by_amount_range,
            "by_date": by_date,
            "top_deals": top_deals,
        },
        "profiles": {
            "total": profiles_count,
            "enrichment_dist": enrichment_dist,
            "sector_dist": sector_dist,
        }
    }


def get_dynamodb_data():
    """Extract data from DynamoDB tables."""
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    client = boto3.client(
        "dynamodb",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

    # trendradar-events
    events_table = dynamodb.Table("trendradar-events")
    events_total = events_table.item_count

    events_by_source = {}
    today = datetime.now(timezone.utc).date()
    last_7_days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    events_by_date = {d: 0 for d in last_7_days}

    paginator = client.get_paginator("scan")
    # Scan for source distribution
    src_expr = {"#src": "source"}
    for page in paginator.paginate(TableName="trendradar-events", ProjectionExpression="#src", ExpressionAttributeNames=src_expr):
        for item in page.get("Items", []):
            source = item.get("source", {}).get("S", "unknown")
            events_by_source[source] = events_by_source.get(source, 0) + 1

    # Scan for timeline - get first_seen_at only
    fsa_expr = {"#fsa": "first_seen_at"}
    for page in paginator.paginate(TableName="trendradar-events", ProjectionExpression="#fsa", ExpressionAttributeNames=fsa_expr):
        for item in page.get("Items", []):
            first_seen = item.get("first_seen_at", {}).get("S", "")
            if first_seen:
                try:
                    dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
                    date_str = dt.date().isoformat()
                    if date_str in events_by_date:
                        events_by_date[date_str] += 1
                except (ValueError, TypeError):
                    pass

    # trendradar-funding
    funding_table = dynamodb.Table("trendradar-funding")
    funding_total = funding_table.item_count

    funding_by_source = {}
    for page in paginator.paginate(TableName="trendradar-funding", ProjectionExpression="#src", ExpressionAttributeNames=src_expr):
        for item in page.get("Items", []):
            source = item.get("source", {}).get("S", "unknown")
            funding_by_source[source] = funding_by_source.get(source, 0) + 1

    return {
        "events": {
            "total": events_total,
            "by_source": events_by_source,
            "by_date": [{"date": d, "count": events_by_date[d]} for d in last_7_days],
        },
        "funding": {
            "total": funding_total,
            "by_source": funding_by_source,
        }
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TrendRadar Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg: #0f0f0f;
            --card-bg: #1a1a1a;
            --card-border: #2a2a2a;
            --text: #fafafa;
            --text-muted: #a1a1a1;
            --amber: #f59e0b;
            --amber-dim: #b45309;
            --amber-glow: rgba(245, 158, 11, 0.15);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--card-border);
        }
        h1 { font-size: 1.75rem; font-weight: 700; color: var(--amber); }
        .updated { color: var(--text-muted); font-size: 0.875rem; }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .kpi-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 1.25rem;
            text-align: center;
        }
        .kpi-label { font-size: 0.875rem; color: var(--text-muted); margin-bottom: 0.5rem; }
        .kpi-value { font-size: 2.5rem; font-weight: 800; color: var(--amber); line-height: 1; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1.5rem;
        }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 1.5rem;
        }
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1rem;
        }
        .card-title { font-size: 1rem; font-weight: 600; color: var(--text-muted); }
        .chart-container { position: relative; height: 250px; margin-top: 1rem; }
        .chart-container.tall { height: 350px; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td {
            text-align: left;
            padding: 0.625rem 0.75rem;
            font-size: 0.8125rem;
        }
        th { color: var(--text-muted); font-weight: 500; border-bottom: 1px solid var(--card-border); }
        tr:nth-child(even) { background: rgba(255,255,255,0.02); }
        tr:hover { background: rgba(245, 158, 11, 0.05); }
        .badge {
            display: inline-block;
            padding: 0.125rem 0.5rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 500;
            background: var(--amber-glow);
            color: var(--amber);
        }
        .section-title {
            font-size: 1.125rem;
            font-weight: 600;
            margin: 2rem 0 1rem;
            color: var(--text);
        }
        .full-width { grid-column: 1 / -1; }
        .two-col { grid-column: span 2; }
        @media (max-width: 768px) {
            .kpi-grid { grid-template-columns: repeat(2, 1fr); }
            .grid { grid-template-columns: 1fr; }
            .two-col { grid-column: 1; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>TrendRadar Dashboard</h1>
            <span class="updated">Updated: {{UPDATED}}</span>
        </header>

        <!-- 4 KPI Cards -->
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Total Events</div>
                <div class="kpi-value">{{EVENTS_TOTAL}}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Pain Signals</div>
                <div class="kpi-value">{{PAIN_TOTAL}}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Clusters</div>
                <div class="kpi-value">{{OPP_TOTAL}}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">SEC Filings</div>
                <div class="kpi-value">{{FILINGS_TOTAL}}</div>
            </div>
        </div>

        <!-- Events by Source -->
        <h2 class="section-title">Events by Source</h2>
        <div class="grid">
            <div class="card full-width">
                <div class="card-title">Events by Source</div>
                <div class="chart-container"><canvas id="eventsBySource"></canvas></div>
            </div>
        </div>

        <!-- Pain Signals & Clusters -->
        <h2 class="section-title">Pain Signals & Opportunity Clusters</h2>
        <div class="grid">
            <div class="card">
                <div class="card-title">Pain Signals by Source</div>
                <div class="chart-container"><canvas id="painBySource"></canvas></div>
            </div>
            <div class="card">
                <div class="card-title">Cluster Score Histogram</div>
                <div class="chart-container"><canvas id="oppScoreDist"></canvas></div>
            </div>
        </div>

        <!-- Top 10 Clusters Table -->
        <h2 class="section-title">Top 10 Opportunity Clusters</h2>
        <div class="grid">
            <div class="card full-width">
                <table>
                    <thead><tr><th>#</th><th>Title</th><th>total_score</th><th>pain_score</th><th>timing_score</th><th>cross_source</th></tr></thead>
                    <tbody id="topClustersTable"></tbody>
                </table>
            </div>
        </div>

        <!-- SEC Amount & Industry Distribution -->
        <h2 class="section-title">SEC Form D Filings</h2>
        <div class="grid">
            <div class="card">
                <div class="card-title">Amount Distribution</div>
                <div class="chart-container"><canvas id="filingsAmount"></canvas></div>
            </div>
            <div class="card">
                <div class="card-title">Industry Distribution</div>
                <div class="chart-container"><canvas id="filingsIndustry"></canvas></div>
            </div>
        </div>

        <!-- Enrichment & Sector -->
        <h2 class="section-title">Company Profiles</h2>
        <div class="grid">
            <div class="card">
                <div class="card-title">Enrichment Quality</div>
                <div class="chart-container"><canvas id="enrichmentQuality"></canvas></div>
            </div>
            <div class="card">
                <div class="card-title">Sector Distribution</div>
                <div class="chart-container tall"><canvas id="sectorDist"></canvas></div>
            </div>
        </div>

        <!-- Last 7 Days Events -->
        <h2 class="section-title">Last 7 Days Events</h2>
        <div class="grid">
            <div class="card full-width">
                <div class="chart-container"><canvas id="eventsTimeline"></canvas></div>
            </div>
        </div>

        <!-- Top 10 SEC Deals -->
        <h2 class="section-title">Top 10 SEC Deals</h2>
        <div class="grid">
            <div class="card full-width">
                <table>
                    <thead><tr><th>#</th><th>Entity Name</th><th>Amount</th><th>Industry Group</th><th>Filing Date</th></tr></thead>
                    <tbody id="topDealsTable"></tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
    const DATA = {{DATA}};

    const AMBER = '#f59e0b';
    const AMBER_DIM = '#b45309';
    const CHART_OPTS = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { labels: { color: '#a1a1a1' } }
        },
        scales: {
            x: { ticks: { color: '#a1a1a1' }, grid: { color: '#2a2a2a' } },
            y: { ticks: { color: '#a1a1a1' }, grid: { color: '#2a2a2a' } }
        }
    };
    const PIE_OPTS = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'right', labels: { color: '#a1a1a1' } } }
    };
    const HBarOpts = {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: { legend: { labels: { color: '#a1a1a1' } } },
        scales: {
            x: { ticks: { color: '#a1a1a1' }, grid: { color: '#2a2a2a' } },
            y: { ticks: { color: '#a1a1a1' }, grid: { color: '#2a2a2a' } }
        }
    };

    // Events by Source (horizontal bar)
    new Chart(document.getElementById('eventsBySource'), {
        type: 'bar',
        data: {
            labels: Object.keys(DATA.events.by_source),
            datasets: [{ label: 'Events', data: Object.values(DATA.events.by_source), backgroundColor: AMBER, borderRadius: 4 }]
        },
        options: HBarOpts
    });

    // Pain Signals by Source (pie)
    new Chart(document.getElementById('painBySource'), {
        type: 'pie',
        data: {
            labels: Object.keys(DATA.pain_signals.by_source),
            datasets: [{ data: Object.values(DATA.pain_signals.by_source), backgroundColor: [AMBER, AMBER_DIM, '#fbbf24', '#d97706', '#92400e', '#78350f'], borderColor: '#0f0f0f', borderWidth: 2 }]
        },
        options: PIE_OPTS
    });

    // Cluster Score Histogram
    new Chart(document.getElementById('oppScoreDist'), {
        type: 'bar',
        data: {
            labels: ['0-0.1','0.1-0.2','0.2-0.3','0.3-0.4','0.4-0.5','0.5-0.6','0.6-0.7','0.7-0.8','0.8-0.9','0.9-1.0'],
            datasets: [{ label: 'Clusters', data: DATA.opportunities.score_histogram, backgroundColor: AMBER, borderRadius: 4 }]
        },
        options: CHART_OPTS
    });

    // Top 10 Clusters Table
    const topClustersTable = document.getElementById('topClustersTable');
    DATA.opportunities.top_10.forEach((opp, i) => {
        topClustersTable.innerHTML += `<tr><td>${i+1}</td><td>${opp.title}</td><td><span class="badge">${opp.total_score}</span></td><td>${opp.pain_score}</td><td>${opp.timing_score}</td><td>${opp.cross_source_count}</td></tr>`;
    });

    // SEC Amount Distribution
    new Chart(document.getElementById('filingsAmount'), {
        type: 'bar',
        data: {
            labels: DATA.filings.by_amount_range.map(d => d.range),
            datasets: [{ label: 'Filings', data: DATA.filings.by_amount_range.map(d => d.count), backgroundColor: AMBER, borderRadius: 4 }]
        },
        options: CHART_OPTS
    });

    // SEC Industry Distribution (horizontal bar)
    new Chart(document.getElementById('filingsIndustry'), {
        type: 'bar',
        data: {
            labels: DATA.filings.by_industry.map(d => d.industry.substring(0, 25)),
            datasets: [{ label: 'Filings', data: DATA.filings.by_industry.map(d => d.count), backgroundColor: AMBER_DIM, borderRadius: 4 }]
        },
        options: HBarOpts
    });

    // Company Profiles - Enrichment Quality
    new Chart(document.getElementById('enrichmentQuality'), {
        type: 'pie',
        data: {
            labels: DATA.profiles.enrichment_dist.map(d => d.quality || 'Unknown'),
            datasets: [{ data: DATA.profiles.enrichment_dist.map(d => d.count), backgroundColor: [AMBER, AMBER_DIM, '#fbbf24', '#d97706'], borderColor: '#0f0f0f', borderWidth: 2 }]
        },
        options: PIE_OPTS
    });

    // Company Profiles - Sector Distribution (horizontal bar)
    new Chart(document.getElementById('sectorDist'), {
        type: 'bar',
        data: {
            labels: DATA.profiles.sector_dist.map(d => d.sector || 'Unknown'),
            datasets: [{ label: 'Companies', data: DATA.profiles.sector_dist.map(d => d.count), backgroundColor: AMBER, borderRadius: 4 }]
        },
        options: HBarOpts
    });

    // Last 7 Days Events (line chart)
    new Chart(document.getElementById('eventsTimeline'), {
        type: 'line',
        data: {
            labels: DATA.events.by_date.map(d => d.date),
            datasets: [{ label: 'Events', data: DATA.events.by_date.map(d => d.count), borderColor: AMBER, backgroundColor: 'rgba(245,158,11,0.1)', fill: true, tension: 0.3 }]
        },
        options: { ...CHART_OPTS, elements: { point: { radius: 4, hoverRadius: 6 } } }
    });

    // Top 10 SEC Deals Table
    const topDealsTable = document.getElementById('topDealsTable');
    DATA.filings.top_deals.forEach(deal => {
        const amt = deal.amount ? '$' + (deal.amount / 1e6).toFixed(1) + 'M' : '-';
        topDealsTable.innerHTML += `<tr><td>${deal.rank}</td><td>${deal.entity_name}</td><td><span class="badge">${amt}</span></td><td>${deal.industry_group}</td><td>${deal.filing_date}</td></tr>`;
    });
    </script>
</body>
</html>
"""


def generate_dashboard():
    """Generate the dashboard HTML file."""
    print("Extracting ChromaDB data...")
    chroma_data = get_chroma_data()

    print("Extracting SQLite data...")
    sqlite_data = get_sqlite_data()

    print("Extracting DynamoDB data...")
    dynamo_data = get_dynamodb_data()

    # Combine all data
    dashboard_data = {
        "pain_signals": chroma_data["pain_signals"],
        "opportunities": chroma_data["opportunities"],
        "filings": sqlite_data["filings"],
        "profiles": sqlite_data["profiles"],
        "events": dynamo_data["events"],
        "funding": dynamo_data["funding"],
    }

    # 4 KPI stats
    top_stats = {
        "EVENTS_TOTAL": dashboard_data["events"]["total"],
        "PAIN_TOTAL": dashboard_data["pain_signals"]["total"],
        "OPP_TOTAL": dashboard_data["opportunities"]["total"],
        "FILINGS_TOTAL": dashboard_data["filings"]["total"],
    }

    # Generate HTML
    html = HTML_TEMPLATE
    html = html.replace("{{DATA}}", json.dumps(dashboard_data))
    html = html.replace("{{UPDATED}}", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    for key, val in top_stats.items():
        html = html.replace(f"{{{key}}}", str(val))

    # Ensure reports directory exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Write output
    OUTPUT_FILE.write_text(html)
    print(f"Dashboard generated: {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_dashboard()