"""AI-powered pain point pre-filter using Xiaomi MiMo v2.5.

Filters pain signals before DynamoDB write to remove noise
(non-startup-related content, pure venting, spam, etc.).
"""

import json
import os
import re
import signal
import threading
import time
import logging
from collections import Counter

import requests
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

MIMO_ENDPOINT = "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"
MIMO_MODEL = "mimo-v2.5"
REQUEST_TIMEOUT = 30
BATCH_TIMEOUT = 120  # seconds for entire batch
CALL_INTERVAL = 0.3  # seconds between calls
MAX_TOKENS = 200

FILTER_PROMPT = '''You are a startup pain point analyzer. Determine if this social media post expresses a REAL PAIN POINT — someone who is actively suffering, losing time/money, or has already tried solutions that failed.

VALID signals (must meet at least ONE):
- Already spending money/time on a workaround (proven willingness to pay)
- Explicit frustration with current solution ("I hate...", "I can\'t believe...", "waste of time")
- Actively seeking alternatives ("looking for alternative", "migrating from", "switching to")
- Churn behavior ("cancelled my...", "dropped...", "leaving X for...")
- Failed to find any solution after trying ("tried everything", "nothing works")
- Willingness to pay stated or implied ("I\'d pay for...", "take my money")

INVALID (reject):
- "I wish there was..." (aspirational, no proven pain)
- "Someone should build..." (idea, not pain)
- "I built X" / "Show HN:" (self-promotion, side project)
- "Any tips for..." (information request, not product need)
- Pure emotional venting without actionable need
- Political/social opinions
- Customer service complaints about specific companies (unless a pattern)
- Crypto/spam/promotional content
- Sports/entertainment opinions
- Vague feature requests ("would be nice if...")

Post: "{text}"
Author followers: {followers}
Engagement: {favorites} likes, {retweets} retweets, {views} views

IMPORTANT: You MUST respond with ONLY valid JSON, no other text, no markdown, no explanation outside JSON:
{{"is_valid": true, "reason": "one sentence"}} or {{"is_valid": false, "reason": "one sentence"}}'''


class PainFilter:
    """Pre-filter pain signals using Xiaomi MiMo v2.5."""

    def __init__(self):
        self.stats = {"total": 0, "passed": 0, "rejected": 0, "errors": 0}
        self.reject_reasons: Counter = Counter()
        self._mimo_key = self._get_mimo_key()

    def _get_mimo_key(self) -> str:
        """Get MIMO API key from env or openclaw config."""
        key = os.environ.get("MIMO_API_KEY", "")
        if not key:
            config_path = os.path.expanduser("~/.openclaw/openclaw.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    _cfg = json.load(f)
                key = _cfg.get("env", {}).get("MIMO_API_KEY", "")
        return key

    def _call_model(self, prompt: str) -> str | None:
        """Call MiMo v2.5, falling back to DeepSeek then Ollama."""
        # Try MiMo first
        if self._mimo_key:
            try:
                resp = requests.post(
                    MIMO_ENDPOINT,
                    headers={"Authorization": f"Bearer {self._mimo_key}"},
                    json={
                        "model": MIMO_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens": MAX_TOKENS,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "") or None
            except requests.exceptions.RequestException as e:
                logger.warning("MiMo request failed: %s, trying fallback", e)

        # Fallback to DeepSeek
        ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if ds_key:
            try:
                resp = requests.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {ds_key}"},
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens": MAX_TOKENS,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "") or None
            except requests.exceptions.RequestException as e:
                logger.warning("DeepSeek fallback failed: %s", e)

        # Fallback to Ollama
        try:
            resp = requests.post(
                "http://localhost:11434/v1/chat/completions",
                json={
                    "model": "gemma4:31b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 500,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if not content.strip():
                content = message.get("reasoning", "")
            return content or None
        except requests.exceptions.RequestException as e:
            logger.warning("Ollama fallback failed: %s", e)
            return None

    def _parse_response(self, raw: str) -> tuple[bool, str]:
        """Parse JSON response from model output, with keyword fallback."""
        # Try to extract JSON from the response
        # Model may wrap in markdown code blocks or add extra text
        json_match = re.search(r'\{[^{}]*"is_valid"[^{}]*\}', raw, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
                is_valid = result.get("is_valid", False)
                reason = result.get("reason", "no reason provided")
                return bool(is_valid), str(reason)
            except json.JSONDecodeError:
                pass

        # Fallback 1: try looser JSON match (boolean literals without quotes)
        json_match2 = re.search(r'\{[^{}]*is_valid[^{}]*\}', raw, re.DOTALL)
        if json_match2:
            try:
                fixed = json_match2.group()
                # Fix unquoted booleans: is_valid: true -> "is_valid": true
                fixed = re.sub(r'(is_valid)\s*:\s*(true|false)', r'"\1": \2', fixed)
                result = json.loads(fixed)
                is_valid = result.get("is_valid", False)
                reason = result.get("reason", "parsed_from_loose_json")
                return bool(is_valid), str(reason)
            except (json.JSONDecodeError, Exception):
                pass

        # Fallback 2: keyword-based classification when JSON parsing fails
        raw_lower = raw.lower()
        # Positive keywords: model is saying it's valid
        positive_patterns = [
            r'\bis_valid\s*(?:=|:)\s*true',
            r'\bvalid\b.*\bpain\b',
            r'\bvalid\b.*\bstartup\b',
            r'\byes\b.*\bvalid\b',
            r'\bthis (?:is|appears to be) (?:a )?valid\b',
            r'\bgenuine (?:need|pain|signal)\b',
        ]
        # Negative keywords: model is saying it's invalid
        negative_patterns = [
            r'\bis_valid\s*(?:=|:)\s*false',
            r'\bnot (?:a )?valid\b',
            r'\binvalid\b',
            r'\bnot (?:a )?(?:startup|pain|business)\b',
            r'\bdoes not (?:express|indicate|show)\b',
            r'\breject\b',
        ]

        pos_score = sum(1 for p in positive_patterns if re.search(p, raw_lower))
        neg_score = sum(1 for p in negative_patterns if re.search(p, raw_lower))

        if pos_score > neg_score:
            return True, "keyword_fallback_positive"
        elif neg_score > 0:
            return False, "keyword_fallback_negative"
        else:
            # Last resort: conservatively pass through
            return True, "unparseable_passed_through"

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

        raw = self._call_model(user_prompt)
        if raw is None:
            # On error, conservatively pass through (don't lose data)
            return True, "deepseek_unavailable_passed_through"

        return self._parse_response(raw)

    def filter_batch(self, items: list[dict]) -> list[dict]:
        """Filter a batch of twitter_pain items with total timeout protection.

        Args:
            items: List of twitter_pain item dicts (with 'title' and 'metadata' keys).

        Returns:
            List of items that passed the filter, each with added 'filter_reason' field.
            If batch times out (120s), returns all items passed so far + remaining items pass-through.
        """
        if not items:
            return []

        self.stats = {"total": 0, "passed": 0, "rejected": 0, "errors": 0}
        self.reject_reasons = Counter()
        passed = []
        timed_out = False

        def timeout_handler():
            nonlocal timed_out
            timed_out = True
            logger.warning("PainFilter batch timeout after %ds, passing through remaining items", BATCH_TIMEOUT)

        # Use threading.Timer for cross-platform timeout
        timer = threading.Timer(BATCH_TIMEOUT, timeout_handler)
        timer.start()

        try:
            for i, item in enumerate(items):
                if timed_out:
                    # Pass through remaining items
                    item["filter_reason"] = "batch_timeout_passed_through"
                    passed.append(item)
                    self.stats["total"] += 1
                    self.stats["passed"] += 1
                    continue

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
        finally:
            timer.cancel()

        self._print_stats()
        return passed

    def _print_stats(self):
        """Print filter statistics using Rich."""
        console.print(f"\n[bold]🔍 Pain Filter Results (DeepSeek V4 Flash)[/bold]")
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
