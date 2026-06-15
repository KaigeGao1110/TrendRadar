"""Embedding client using OpenRouter (openai/text-embedding-3-small).

Generates 1536-dim vectors for text.
"""

import math
import os
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/embeddings"
MODEL = "openai/text-embedding-3-small"
RATE_LIMIT_INTERVAL = 0.5  # seconds between calls
DIMENSION = 1536


def _get_openrouter_key() -> str:
    """Get OpenRouter API key from env or openclaw config."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")
        if os.path.exists(config_path):
            import json
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            key = cfg.get("env", {}).get("OPENROUTER_API_KEY", "")
    return key


class EmbeddingClient:
    """Generate embeddings using OpenRouter (text-embedding-3-small)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or _get_openrouter_key()
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set. Set it in .env or pass api_key=.")
        self._last_call = 0.0

    def _rate_limit(self) -> None:
        """Enforce minimum interval between API calls."""
        elapsed = time.monotonic() - self._last_call
        if elapsed < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self._last_call = time.monotonic()

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text. Returns 1536-dim vector.

        Args:
            text: Input text to embed.

        Returns:
            List of 1536 floats.

        Raises:
            RuntimeError: After 3 failed attempts.
        """
        if not text or not text.strip():
            return [0.0] * DIMENSION

        self._rate_limit()
        last_err = None

        for attempt in range(3):
            try:
                resp = requests.post(
                    OPENROUTER_API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MODEL,
                        "input": text,
                    },
                    timeout=45,
                )

                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Embedding API error {resp.status_code}: {resp.text[:500]}"
                    )

                data = resp.json()
                embedding = data["data"][0]["embedding"]

                if len(embedding) != DIMENSION:
                    logger.warning(
                        "Expected %d dims, got %d", DIMENSION, len(embedding)
                    )

                return embedding
            except Exception as e:
                last_err = e
                logger.warning("Embedding attempt %d failed: %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(2 ** attempt)  # 1s, 2s, 4s

        logger.error("All embedding retries failed for text: %s", text[:100])
        raise RuntimeError(f"Embedding failed after 3 retries: {last_err}")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts. One API call per text.

        Args:
            texts: List of input texts.

        Returns:
            List of 1536-dim vectors, same order as input.
        """
        results = []
        for text in texts:
            embedding = self.embed_text(text)
            results.append(embedding)
        return results
