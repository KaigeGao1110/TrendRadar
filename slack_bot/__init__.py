"""Slack bot for TrendRadar."""

import os
import threading
import requests
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# TrendRadar API URL (for fast cached digest)
API_BASE = os.environ.get("TRENDRADAR_API_URL", "https://trend-radar-594674305905.us-central1.run.app")

# Initialize Slack app
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")

if SLACK_BOT_TOKEN and SLACK_APP_TOKEN:
    app = App(token=SLACK_BOT_TOKEN)
else:
    app = None


def _post_async(say_fn, url_path: str, fallback_text: str):
    """Fetch from API and post result via say()."""
    def worker():
        try:
            resp = requests.get(f"{API_BASE}{url_path}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                text = _format_digest(data)
                say_fn(text=text)
            else:
                say_fn(text=f"⚠️ Could not fetch latest digest ({resp.status_code}). Try again soon.")
        except Exception as e:
            say_fn(text=f"❌ Error: {e}")

    say_fn(text="⏳ Fetching latest trends...")
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def _format_digest(data: dict) -> str:
    """Format a digest dict for Slack text output."""
    cats = data.get("hot_categories", [])
    signals = data.get("vc_signals", [])
    patterns = data.get("emerging_patterns", [])
    recs = data.get("recommendations", [])

    date_str = data.get("date", "today")
    lines = [
        f"🔥 *TrendRadar Daily — {date_str}*",
        "",
    ]

    if cats:
        lines.append("*🔥 Hot Categories*")
        for c in cats[:5]:
            lines.append(f"  • {c}")
        lines.append("")

    if signals:
        lines.append("*💡 Top Signals*")
        for s in signals[:3]:
            lines.append(f"  • {s}")
        lines.append("")

    if patterns:
        lines.append("*📈 Trending Now*")
        for p in patterns[:3]:
            lines.append(f"  • {p[:120]}")
        lines.append("")

    if recs:
        lines.append("*🚀 For Founders*")
        for r in recs[:3]:
            lines.append(f"  • {r}")

    return "\n".join(lines)


@app.command("/trendradar-today")
def handle_today(ack, say, command):
    """Daily digest command."""
    ack()
    _post_async(say, "/digest/latest", "⚠️ No digest available yet.")


@app.command("/trendradar-weekly")
def handle_weekly(ack, say, command):
    """Weekly digest command."""
    ack()
    say(text="📅 Weekly digest coming soon!")


@app.command("/trendradar-yc")
def handle_yc(ack, say, command):
    """Latest YC batch trends."""
    ack()
    _post_async(say, "/sources/ycombinator", "⚠️ Could not fetch YC data.")


@app.command("/trendradar-ph")
def handle_ph(ack, say, command):
    """Today's Product Hunt."""
    ack()
    _post_async(say, "/sources/producthunt", "⚠️ Could not fetch Product Hunt data.")


@app.command("/trendradar-hn")
def handle_hn(ack, say, command):
    """Hacker News trends."""
    ack()
    _post_async(say, "/sources/hackernews", "⚠️ Could not fetch HN data.")


@app.command("/trendradar-funding")
def handle_funding(ack, say, command):
    """Recent VC funding."""
    ack()
    _post_async(say, "/sources/vc_funding", "⚠️ Could not fetch funding data.")


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


def _warm_cache():
    """Pre-populate digest cache on startup."""
    try:
        resp = requests.get(f"{API_BASE}/digest/latest", timeout=10)
        if resp.status_code == 200:
            print(f"[TrendRadar] Cache warmed, latest digest from {resp.json().get('date')}")
        else:
            print(f"[TrendRadar] No cached digest yet ({resp.status_code}), will fetch on demand")
    except Exception as e:
        print(f"[TrendRadar] Cache warmup failed: {e}")


def run_slack_bot():
    """Run the Slack bot with Socket Mode."""
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        print("ERROR: SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set")
        return

    # Warm cache before going live
    _warm_cache()

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
