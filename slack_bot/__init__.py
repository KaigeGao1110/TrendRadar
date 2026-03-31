"""Slack bot for TrendRadar."""

import os
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from analyzer.digest import generate_daily_digest, generate_weekly_digest, format_for_slack
from sources import yc, producthunt, hackernews, vc_funding

# Initialize Slack app
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")

if SLACK_BOT_TOKEN and SLACK_APP_TOKEN:
    app = App(token=SLACK_BOT_TOKEN)
else:
    app = None


@app.command("/trendradar-today")
def handle_today(ack, respond):
    """Daily digest command."""
    ack()
    digest = generate_daily_digest()
    blocks = format_for_slack(digest)["blocks"]
    respond(blocks=blocks)


@app.command("/trendradar-weekly")
def handle_weekly(ack, respond):
    """Weekly digest command."""
    ack()
    digest = generate_weekly_digest()
    blocks = format_for_slack(digest)["blocks"]
    respond(blocks=blocks)


@app.command("/trendradar-yc")
def handle_yc(ack, respond):
    """Latest YC batch trends."""
    ack()
    companies = yc.fetch_latest_batch()
    categories = yc.categorize_companies(companies)
    
    text = "*🔥 Latest YC Batch Trends*\n\n"
    for cat, data in sorted(categories.items(), key=lambda x: x[1]["count"], reverse=True)[:5]:
        text += f"*{cat}* ({data['count']} companies)\n"
        text += " • " + "\n • ".join(data["examples"]) + "\n\n"
    
    respond(text=text)


@app.command("/trendradar-ph")
def handle_ph(ack, respond):
    """Today's Product Hunt."""
    ack()
    products = producthunt.fetch_today_trending()
    categories = producthunt.categorize_products(products)
    
    text = "*🚀 Today's Product Hunt*\n\n"
    for cat, data in sorted(categories.items(), key=lambda x: x[1]["count"], reverse=True)[:5]:
        text += f"*{cat}* ({data['count']} products)\n"
        text += " • " + "\n • ".join(data["products"][:3]) + "\n\n"
    
    respond(text=text)


@app.command("/trendradar-hn")
def handle_hn(ack, respond):
    """Hacker News trends."""
    ack()
    stories = hackernews.fetch_top_stories()
    trends = hackernews.detect_tech_trends(stories)
    
    text = "*📊 Hacker News Trends*\n\n"
    for trend in trends[:5]:
        text += f"*{trend['trend']}* (signal: {trend['signal_strength']})\n"
        text += " • " + "\n • ".join(trend["example_stories"][:2]) + "\n\n"
    
    respond(text=text)


@app.command("/trendradar-funding")
def handle_funding(ack, respond):
    """Recent VC funding."""
    ack()
    funding = vc_funding.fetch_recent_funding()
    categorized = vc_funding.categorize_funding(funding)
    
    text = "*💰 Recent VC Funding*\n\n"
    by_sector = categorized.get("by_sector", {})
    for sector, data in sorted(by_sector.items(), key=lambda x: x[1]["count"], reverse=True)[:5]:
        total = data["total_raised"]
        if total >= 1e6:
            total_str = f"${total/1e6:.1f}M"
        else:
            total_str = f"${total/1e3:.1f}K"
        text += f"*{sector}* — {data['count']} rounds, {total_str}\n"
    
    respond(text=text)


@app.command("/trendradar-help")
def handle_help(ack, respond):
    """Help command."""
    ack()
    text = """
*🔥 TrendRadar Commands*

• `/trendradar-today` — Daily trend digest
• `/trendradar-weekly` — Weekly trend digest
• `/trendradar-yc` — Latest YC batch trends
• `/trendradar-ph` — Today's Product Hunt
• `/trendradar-hn` — Hacker News tech trends
• `/trendradar-funding` — Recent VC funding rounds

_Know what's hot before everyone else._
"""
    respond(text=text)


def run_slack_bot():
    """Run the Slack bot with Socket Mode."""
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        print("ERROR: SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set")
        print("Create .env.slack with these tokens")
        return
    
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
