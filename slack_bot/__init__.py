"""Slack bot for TrendRadar."""

import os
import threading
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


def _respond_async(respond_fn, func, *args, **kwargs):
    """Run a function in a thread and respond with the result.
    Sends an initial 'working...' message, then the real result."""
    def worker():
        try:
            result = func(*args, **kwargs)
            respond_fn(replace_original=True, **result)
        except Exception as e:
            respond_fn(replace_original=True, text=f"❌ Error: {e}")

    # Send immediate loading message
    respond_fn(text="⏳ Fetching trends...")

    # Start background thread
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


@app.command("/trendradar-today")
def handle_today(ack, respond, command):
    """Daily digest command."""
    ack()
    _respond_async(respond, _build_daily_digest)


@app.command("/trendradar-weekly")
def handle_weekly(ack, respond, command):
    """Weekly digest command."""
    ack()
    _respond_async(respond, _build_weekly_digest)


@app.command("/trendradar-yc")
def handle_yc(ack, respond, command):
    """Latest YC batch trends."""
    ack()
    _respond_async(respond, _build_yc_trends)


@app.command("/trendradar-ph")
def handle_ph(ack, respond, command):
    """Today's Product Hunt."""
    ack()
    _respond_async(respond, _build_ph_trends)


@app.command("/trendradar-hn")
def handle_hn(ack, respond, command):
    """Hacker News trends."""
    ack()
    _respond_async(respond, _build_hn_trends)


@app.command("/trendradar-funding")
def handle_funding(ack, respond, command):
    """Recent VC funding."""
    ack()
    _respond_async(respond, _build_funding_trends)


@app.command("/trendradar-help")
def handle_help(ack, respond):
    """Help command."""
    ack()
    text = """
*🔥 TrendRadar Commands*

• `/trendradar-today` — AI-powered daily trend digest
• `/trendradar-weekly` — Weekly trend analysis
• `/trendradar-yc` — Latest YC batch companies
• `/trendradar-ph` — Today's Product Hunt top products
• `/trendradar-hn` — Hacker News tech trends
• `/trendradar-funding` — Recent VC funding rounds

_Know what's hot before everyone else._
"""
    respond(text=text)


# ---------------------------------------------------------------------------
# Builder functions (run in threads)
# ---------------------------------------------------------------------------

def _build_daily_digest() -> dict:
    """Build daily digest response."""
    digest = generate_daily_digest()
    blocks = format_for_slack(digest)
    return {"blocks": blocks}


def _build_weekly_digest() -> dict:
    """Build weekly digest response."""
    digest = generate_weekly_digest()
    blocks = format_for_slack(digest)
    return {"blocks": blocks}


def _build_yc_trends() -> dict:
    """Build YC trends response."""
    companies = yc.fetch_latest_batch()
    categories = yc.categorize_companies(companies)

    text = f"*🔥 Latest YC Batch* ({len(companies)} companies)\n\n"
    for cat, data in sorted(categories.items(), key=lambda x: x[1]["count"], reverse=True)[:8]:
        text += f"*{cat}* ({data['count']})\n"
        for ex in data.get("examples", [])[:2]:
            text += f"  • {ex}\n"
        text += "\n"

    return {"text": text}


def _build_ph_trends() -> dict:
    """Build Product Hunt response."""
    products = producthunt.fetch_today_trending(15)

    text = f"*🚀 Today's Product Hunt* ({len(products)} products)\n\n"
    for i, p in enumerate(products[:10], 1):
        tagline = p.get("tagline", "")[:60]
        topics = ", ".join(p.get("topics", [])[:3])
        text += f"*{i}. {p['name']}*\n"
        if tagline:
            text += f"  {tagline}\n"
        if topics:
            text += f"  _{topics}_\n"
        text += "\n"

    return {"text": text}


def _build_hn_trends() -> dict:
    """Build Hacker News response."""
    stories = hackernews.fetch_top_stories(15)

    text = f"*📊 Hacker News Top Stories*\n\n"
    for i, s in enumerate(stories[:10], 1):
        score = s.get("score", 0)
        title = s.get("title", "")
        url = s.get("url", "")
        text += f"*{i}. {title}* ({score}pts)\n"
        if url:
            text += f"  <{url}|Link>\n"
        text += "\n"

    return {"text": text}


def _build_funding_trends() -> dict:
    """Build VC funding response."""
    funding = vc_funding.fetch_recent_funding(days=14)
    categorized = vc_funding.categorize_funding(funding)

    text = f"*💰 Recent VC Funding* ({len(funding)} rounds)\n\n"
    by_sector = categorized.get("by_sector", {})
    for sector, data in sorted(by_sector.items(), key=lambda x: x[1]["count"], reverse=True)[:8]:
        total = data.get("total_raised", 0)
        if total >= 1e6:
            total_str = f"${total/1e6:.1f}M"
        elif total >= 1e3:
            total_str = f"${total/1e3:.0f}K"
        else:
            total_str = f"${total}"
        text += f"*{sector}* — {data['count']} rounds, {total_str}\n"
        for company in data.get("companies", [])[:2]:
            text += f"  • {company}\n"
        text += "\n"

    return {"text": text}


def run_slack_bot():
    """Run the Slack bot with Socket Mode."""
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        print("ERROR: SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set")
        print("Create .env.slack with these tokens")
        return

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
