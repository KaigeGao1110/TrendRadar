"""Embedding client using doubao-embedding-vision via Ark (Volcengine) API.

Generates 2048-dim vectors for text (and future: images).
"""

import math
import os
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ARK_API_KEY = os.environ.get("ARK_API_KEY", "")
EMBEDDING_URL = "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
MODEL = "doubao-embedding-vision-250615"
RATE_LIMIT_INTERVAL = 0.5  # seconds between calls
DIMENSION = 2048


class EmbeddingClient:
    """Generate embeddings using doubao-embedding-vision via Ark API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or ARK_API_KEY
        if not self.api_key:
            raise ValueError("ARK_API_KEY not set. Set it in .env or pass api_key=.")
        self._last_call = 0.0

    def _rate_limit(self) -> None:
        """Enforce minimum interval between API calls."""
        elapsed = time.monotonic() - self._last_call
        if elapsed < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self._last_call = time.monotonic()

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text. Returns 2048-dim vector.

        Args:
            text: Input text to embed.

        Returns:
            List of 2048 floats.

        Raises:
            RuntimeError: If all retries fail.
        """
        self._rate_limit()

        last_err = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    EMBEDDING_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MODEL,
                        "input": [{"type": "text", "text": text}],
                    },
                    timeout=45,
                )

                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Embedding API error {resp.status_code}: {resp.text[:500]}"
                    )

                data = resp.json()
                embedding = data["data"]["embedding"]

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
            List of 2048-dim vectors, same order as input.
        """
        results = []
        for i, text in enumerate(texts):
            logger.debug("Embedding text %d/%d", i + 1, len(texts))
            embedding = self.embed_text(text)
            results.append(embedding)
        return results

    def embed_image(self, image_url: str) -> list[float]:
        """Generate embedding for an image. (future use)

        Args:
            image_url: URL of the image to embed.

        Returns:
            List of 2048 floats.

        Raises:
            RuntimeError: If the API call fails.
        """
        self._rate_limit()

        resp = requests.post(
            EMBEDDING_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "input": [{"type": "image_url", "image_url": image_url}],
            },
            timeout=60,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Embedding API error {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        return data["data"]["embedding"]

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            a: First vector.
            b: Second vector.

        Returns:
            Cosine similarity in [-1, 1].
        """
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
