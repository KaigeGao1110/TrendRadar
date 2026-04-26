"""AI-powered pain point pre-filter using local gemma4:31b via Ollama.

Filters Twitter pain signals before DynamoDB write to remove noise
(non-startup-related content, pure venting, spam, etc.).
"""

import json
import re
import time
import logging
from collections import Counter

import requests
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

OLLAMA_ENDPOINT = "http://localhost:11434/v1/chat/completions"
MODEL_NAME = "gemma4:31b"
REQUEST_TIMEOUT = 60
CALL_INTERVAL = 0.3  # seconds between calls to avoid Ollama overload
MAX_TOKENS = 500  # gemma4 thinking models need more tokens

FILTER_PROMPT = '''You are a startup pain point analyzer. Determine if this social media post expresses a genuine need for a product, tool, or service that could be built as a startup.

VALID signals:
- "I wish there was a tool to..."
- "Someone should build..."
- "Why is there no way to..."
- "Looking for a tool that..."
- Explicit frustration with a process that could be automated/solved
- Request for recommendations for tools/solutions

INVALID (reject):
- Pure emotional venting without actionable need
- Political/social opinions
- Customer service complaints about specific companies (unless pattern)
- Crypto/spam/promotional content
- Personal life frustrations
- Sports/entertainment opinions

Post: "{text}"
Author followers: {followers}
Engagement: {favorites} likes, {retweets} retweets, {views} views

Respond in JSON only:
{{"is_valid": true/false, "reason": "one sentence explanation"}}'''


class PainFilter:
    """Pre-filter pain signals using local gemma4:31b model."""

    def __init__(self):
        self.stats = {"total": 0, "passed": 0, "rejected": 0, "errors": 0}
        self.reject_reasons: Counter = Counter()

    def _call_ollama(self, prompt: str) -> str | None:
        """Call Ollama OpenAI-compatible endpoint."""
        try:
            resp = requests.post(
                OLLAMA_ENDPOINT,
                json={
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": MAX_TOKENS,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning("Ollama request failed: %s", e)
            return None

        # Extract response text - handle thinking models
        choices = data.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        content = message.get("content", "")

        # gemma4 is a thinking model: if content is empty, try reasoning field
        if not content.strip():
            content = message.get("reasoning", "")
            if not content:
                return None

        return content

    def _parse_response(self, raw: str) -> tuple[bool, str]:
        """Parse JSON response from model output."""
        # Try to extract JSON from the response
        # Model may wrap in markdown code blocks or add extra text
        json_match = re.search(r'\{[^{}]*"is_valid"[^{}]*\}', raw, re.DOTALL)
        if not json_match:
            # Fallback: if we can't parse, reject conservatively
            return False, "failed_to_parse_model_response"

        try:
            result = json.loads(json_match.group())
            is_valid = result.get("is_valid", False)
            reason = result.get("reason", "no reason provided")
            return bool(is_valid), str(reason)
        except json.JSONDecodeError:
            return False, "json_decode_error"

    def is_valid_pain(self, text: str, metadata: dict | None = None) -> tuple[bool, str]:
        """Determine if a tweet is a valid startup pain signal.

        Args:
            text: Tweet text content.
            metadata: Optional metadata dict with engagement stats.

        Returns:
            (is_valid, reason) tuple.
        """
        if not text or not text.strip():
            return False, "empty_text"

        meta = metadata or {}
        followers = meta.get("followers_count", "N/A")
        favorites = meta.get("favorites", 0)
        retweets = meta.get("retweets", 0)
        views = meta.get("views", 0)

        user_prompt = FILTER_PROMPT.format(
            text=text,
            followers=followers,
            favorites=favorites,
            retweets=retweets,
            views=views,
        )

        raw = self._call_ollama(user_prompt)
        if raw is None:
            # On error, conservatively pass through (don't lose data)
            return True, "ollama_unavailable_passed_through"

        return self._parse_response(raw)

    def filter_batch(self, items: list[dict]) -> list[dict]:
        """Filter a batch of twitter_pain items.

        Args:
            items: List of twitter_pain item dicts (with 'title' and 'metadata' keys).

        Returns:
            List of items that passed the filter, each with added 'filter_reason' field.
        """
        if not items:
            return []

        self.stats = {"total": 0, "passed": 0, "rejected": 0, "errors": 0}
        self.reject_reasons = Counter()
        passed = []

        for i, item in enumerate(items):
            text = item.get("title", "") or item.get("description", "")
            metadata = item.get("metadata", {})

            self.stats["total"] += 1
            is_valid, reason = self.is_valid_pain(text, metadata)

            if is_valid:
                self.stats["passed"] += 1
                item["filter_reason"] = reason
                passed.append(item)
            else:
                self.stats["rejected"] += 1
                self.reject_reasons[reason] += 1

            # Rate limit
            if i < len(items) - 1:
                time.sleep(CALL_INTERVAL)

        self._print_stats()
        return passed

    def _print_stats(self):
        """Print filter statistics using Rich."""
        console.print(f"\n[bold]🔍 Pain Filter Results (gemma4:31b)[/bold]")
        console.print(f"  Total: {self.stats['total']}")
        console.print(f"  [green]Passed: {self.stats['passed']}[/green]")
        console.print(f"  [red]Rejected: {self.stats['rejected']}[/red]")
        if self.stats["errors"]:
            console.print(f"  [yellow]Errors: {self.stats['errors']}[/yellow]")

        if self.reject_reasons:
            table = Table(title="Top Rejection Reasons", show_header=True)
            table.add_column("Reason", style="red")
            table.add_column("Count", style="dim", justify="right")
            for reason, count in self.reject_reasons.most_common(5):
                table.add_row(reason, str(count))
            console.print(table)
