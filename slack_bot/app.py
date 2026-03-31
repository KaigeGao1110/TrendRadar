"""Slack Bot for TrendRadar - Socket Mode."""

import os
import logging
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from analyzer.digest import generate_daily_digest, generate_weekly_digest, format_for_slack
from slack_bot.commands import register_commands

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Slack app
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)

# Register slash commands
register_commands(app)


@app.event("app_mention")
def handle_app_mention(event, say):
    """Handle app mention events."""
    say(f"Hi <@{event['user']}>! Use `/trendradar-help` for available commands.")


@app.event("message")
def handle_message(event, say):
    """Handle direct messages."""
    # Ignore bot messages
    if event.get("bot_id"):
        return
    say("Thanks for messaging TrendRadar! Use `/trendradar-help` for available commands.")


def run_slack_bot():
    """Run the Slack bot with Socket Mode."""
    handler = SocketModeHandler(
        app_token=os.environ.get("SLACK_APP_TOKEN"),
        app=app
    )
    handler.start()


if __name__ == "__main__":
    run_slack_bot()
