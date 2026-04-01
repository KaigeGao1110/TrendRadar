"""Daily digest sender for TrendRadar Slack bot."""

import os
import logging
from datetime import date
from pathlib import Path

from slack_sdk import WebClient

from analyzer.digest import generate_daily_digest, format_for_slack
from storage import get_latest_digest

logger = logging.getLogger(__name__)

# Path to track last sent date
_STATE_DIR = Path(__file__).parent.parent / "data"
_LAST_DIGEST_FILE = _STATE_DIR / ".last_digest_sent"


def should_send_digest() -> bool:
    """Check if the daily digest should be sent (once per day).

    Returns:
        True if digest hasn't been sent yet today, False otherwise.
    """
    _STATE_DIR.mkdir(parents=True, exist_ok=True)

    if not _LAST_DIGEST_FILE.exists():
        return True

    try:
        last_sent = _LAST_DIGEST_FILE.read_text().strip()
        today = str(date.today())
        if last_sent == today:
            logger.info("Digest already sent today (%s). Skipping.", today)
            return False
        return True
    except Exception as e:
        logger.warning("Failed to read last digest state: %s. Will send digest.", e)
        return True


def _mark_digest_sent() -> None:
    """Mark today's digest as sent."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _LAST_DIGEST_FILE.write_text(str(date.today()))
    logger.info("Digest sent for %s", date.today())


def send_daily_digest(channel_id: str = None) -> dict:
    """Send the daily trend digest to Slack.

    Generates a fresh digest, formats it for Slack, and sends it.
    Tracks send state to ensure only one digest per day.

    Args:
        channel_id: Slack channel ID to post to. If not provided,
            reads SLACK_CHANNEL_ID from environment.

    Returns:
        {"ok": bool, "message": str, "digest_date": str}
    """
    if not should_send_digest():
        return {
            "ok": False,
            "message": f"Digest already sent today ({date.today()}).",
            "digest_date": str(date.today()),
        }

    # Get Slack token
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        logger.error("SLACK_BOT_TOKEN not set")
        return {"ok": False, "message": "SLACK_BOT_TOKEN not configured", "digest_date": str(date.today())}

    # Determine channel
    if not channel_id:
        channel_id = os.environ.get("SLACK_CHANNEL_ID")
    if not channel_id:
        logger.error("No channel_id provided or SLACK_CHANNEL_ID not set")
        return {"ok": False, "message": "No channel_id provided", "digest_date": str(date.today())}

    # Generate digest
    try:
        digest = generate_daily_digest()
    except Exception as e:
        logger.error("Failed to generate digest: %s", e)
        return {"ok": False, "message": f"Failed to generate digest: {e}", "digest_date": str(date.today())}

    # Format for Slack
    slack_message = format_for_slack(digest)

    # Send to Slack
    try:
        client = WebClient(token=bot_token)
        result = client.chat_postMessage(channel=channel_id, **slack_message)
        _mark_digest_sent()
        logger.info("Daily digest sent to channel %s", channel_id)
        return {
            "ok": True,
            "message": "Digest sent successfully",
            "digest_date": digest.get("date", str(date.today())),
            "ts": result.get("ts"),
        }
    except Exception as e:
        logger.error("Failed to send digest to Slack: %s", e)
        return {"ok": False, "message": f"Failed to send: {e}", "digest_date": str(date.today())}
