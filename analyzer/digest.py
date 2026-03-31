"""Daily/Weekly digest generation."""

from datetime import datetime, date, timedelta
from typing import Optional

from sources import yc, producthunt, hackernews, vc_funding
from analyzer.trends import analyze_daily_trends, generate_trend_summary
from storage import save_digest, get_latest_digest


def generate_daily_digest() -> dict:
    """Generate a daily trend digest from all sources.
    
    Returns:
        {date, sources_count, hot_categories[], top_signals[], summary, raw_data}
    """
    # Fetch data from all sources
    all_data = {}
    
    try:
        yc_data = yc.fetch_latest_batch()
        all_data["ycombinator"] = yc_data
    except Exception as e:
        all_data["ycombinator"] = []
    
    try:
        ph_data = producthunt.fetch_today_trending()
        all_data["producthunt"] = ph_data
    except Exception as e:
        all_data["producthunt"] = []
    
    try:
        hn_data = hackernews.fetch_top_stories(limit=30)
        all_data["hackernews"] = hn_data
    except Exception as e:
        all_data["hackernews"] = []
    
    try:
        vc_data = vc_funding.fetch_recent_funding(days=7)
        all_data["vc_funding"] = vc_data
    except Exception as e:
        all_data["vc_funding"] = []
    
    # Analyze trends
    trends = analyze_daily_trends(all_data)
    
    # Count sources
    sources_count = sum(1 for v in all_data.values() if v)
    
    digest = {
        "date": str(date.today()),
        "generated_at": datetime.now().isoformat(),
        "sources_count": sources_count,
        "sources_fetched": list(all_data.keys()),
        "hot_categories": trends.get("hot_categories", []),
        "top_signals": trends.get("vc_signals", [])[:5],
        "emerging_patterns": trends.get("emerging_patterns", []),
        "recommendations": trends.get("recommendations", []),
        "summary": generate_trend_summary(trends),
        "raw_data": all_data,
        "raw_analysis": trends.get("raw_analysis", ""),
    }
    
    save_digest(digest)
    return digest


def generate_weekly_digest() -> dict:
    """Generate a weekly trend digest with deeper analysis."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    
    # Fetch weekly data
    all_data = {}
    
    try:
        yc_data = yc.fetch_all_batches_since(today.year)
        all_data["ycombinator"] = yc_data
    except Exception:
        all_data["ycombinator"] = []
    
    try:
        ph_data = producthunt.fetch_weekly_top(limit=50)
        all_data["producthunt"] = ph_data
    except Exception:
        all_data["producthunt"] = []
    
    try:
        hn_data = hackernews.fetch_top_stories(limit=50)
        all_data["hackernews"] = hn_data
    except Exception:
        all_data["hackernews"] = []
    
    try:
        vc_data = vc_funding.fetch_recent_funding(days=7)
        all_data["vc_funding"] = vc_data
    except Exception:
        all_data["vc_funding"] = []
    
    # Deeper analysis for weekly
    trends = analyze_daily_trends(all_data)
    
    digest = {
        "date": str(today),
        "period": f"{week_ago} to {today}",
        "type": "weekly",
        "generated_at": datetime.now().isoformat(),
        "sources_count": sum(1 for v in all_data.values() if v),
        "hot_categories": trends.get("hot_categories", []),
        "top_signals": trends.get("vc_signals", []),
        "emerging_patterns": trends.get("emerging_patterns", []),
        "recommendations": trends.get("recommendations", []),
        "summary": generate_trend_summary(trends),
        "raw_data": all_data,
        "raw_analysis": trends.get("raw_analysis", ""),
    }
    
    save_digest(digest)
    return digest


def format_for_slack(digest: dict) -> dict:
    """Format digest as Slack Block Kit message."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔥 TrendRadar Daily — {digest.get('date', date.today())}",
                "emoji": True,
            }
        },
        {"type": "divider"},
    ]
    
    # Hot Categories
    if digest.get("hot_categories"):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🔥 Hot Categories*\n" + "\n".join(f"• {c}" for c in digest["hot_categories"][:5])
            }
        })
    
    # Emerging Patterns
    if digest.get("emerging_patterns"):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📈 Emerging Patterns*\n" + "\n".join(f"• {p}" for p in digest["emerging_patterns"][:3])
            }
        })
    
    # Recommendations
    if digest.get("recommendations"):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*💡 For Founders*\n" + "\n".join(f"• {r}" for r in digest["recommendations"][:3])
            }
        })
    
    # Footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Sources: {digest.get('sources_count', 0)} | Generated {digest.get('generated_at', '')[:16]}"
            }
        ]
    })
    
    return {"blocks": blocks}


def format_for_email(digest: dict) -> str:
    """Format digest as HTML email."""
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0;">🔥 TrendRadar</h1>
            <p style="color: rgba(255,255,255,0.8); margin: 5px 0 0;">Daily VC Trend Digest • {digest.get('date', '')}</p>
        </div>
        
        <div style="padding: 20px; background: #f9f9f9;">
            <h2 style="color: #333;">🔥 Hot Categories</h2>
            <ul style="color: #555;">
                {''.join(f'<li>{c}</li>' for c in digest.get('hot_categories', [])[:5])}
            </ul>
            
            <h2 style="color: #333;">📈 Emerging Patterns</h2>
            <ul style="color: #555;">
                {''.join(f'<li>{p}</li>' for p in digest.get('emerging_patterns', [])[:3])}
            </ul>
            
            <h2 style="color: #333;">💡 Recommendations</h2>
            <ul style="color: #555;">
                {''.join(f'<li>{r}</li>' for r in digest.get('recommendations', [])[:3])}
            </ul>
        </div>
        
        <div style="padding: 15px 20px; background: #eee; border-radius: 0 0 8px 8px; font-size: 12px; color: #888;">
            Sources: {digest.get('sources_count', 0)} | Generated {digest.get('generated_at', '')[:16]}
        </div>
    </body>
    </html>
    """
    return html
