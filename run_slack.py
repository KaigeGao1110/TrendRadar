"""Slack bot runner."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load slack credentials
env_path = Path(__file__).parent / ".env.slack"
if env_path.exists():
    load_dotenv(env_path)

from slack_bot import run_slack_bot

if __name__ == "__main__":
    run_slack_bot()
