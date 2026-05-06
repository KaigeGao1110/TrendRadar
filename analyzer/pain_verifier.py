"""Pain verification engine with four-layer validation.

Layer 1: Volume Check (semantic clustering)
Layer 2: Signal Strength (engagement metrics)
Layer 3: Cross-Source (multi-platform verification)
Layer 4: Market Proof (funding/investment signals)
"""

import json
import logging
import re
from typing import Optional

from storage.embedding import EmbeddingClient
from storage.chroma_client import ChromaClient
from storage.dynamo import DynamoClient, FundingClient


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    import math
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    mag_a = math.sqrt(sum(float(x) ** 2 for x in a))
    mag_b = math.sqrt(sum(float(y) ** 2 for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)

logger = logging.getLogger(__name__)

# Pain signal sources (Layer 1)
PAIN_SOURCES = {"twitter_pain", "reddit", "hackernews_comments", "producthunt_deep", "exa_pain", "rss_pain"}

# Similarity threshold for semantic clustering
SIMILARITY_THRESHOLD = 0.5


class PainVerifier:
    """Four-layer pain signal verification engine."""

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        chroma: ChromaClient,
        dynamo: DynamoClient,
        funding_client: Optional[FundingClient] = None,
    ):
        self.embedding = embedding_client
        self.chroma = chroma
        self.dynamo = dynamo
        self.funding = funding_client or FundingClient()

    # ------------------------------------------------------------------
    # Layer 1: Volume Check
    # ------------------------------------------------------------------

    def _volume_score(self, count: int) -> int:
        """Map mention count to volume score."""
        if count >= 10:
            return 70
        if count >= 6:
            return 60
        if count >= 3:
            return 50
        return 30

    def count_similar_pains(self, pain_embedding: list[float], pain_text: str) -> int:
        """Count how many similar pain signals exist via Supabase vector search.

        Includes the current signal itself (count >= 1).
        """
        matches = self.chroma.find_similar_pains(
            embedding=pain_embedding,
            threshold=SIMILARITY_THRESHOLD,
            limit=50,
        )
        return len(matches) + 1  # +1 for the current signal itself

    # ------------------------------------------------------------------
    # Layer 2: Signal Strength
    # ------------------------------------------------------------------

    def _parse_engagement(self, event: dict) -> float:
        """Parse engagement metrics from event data field.

        Returns a weighted engagement score.
        """
        data = event.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = {}

        source = event.get("source", "")

        if source == "twitter_pain":
            favorites = data.get("favorites", 0) or data.get("likes", 0) or 0
            retweets = data.get("retweets", 0) or 0
            replies = data.get("replies", 0) or 0
            return favorites * 0.1 + retweets * 0.5 + replies * 0.3

        if source == "reddit":
            upvotes = data.get("upvotes", 0) or data.get("score", 0) or 0
            comments = data.get("comments", 0) or data.get("num_comments", 0) or 0
            return float(upvotes + comments)

        if source in ("hackernews_comments", "hackernews"):
            score = data.get("score", 0) or 0
            comments = data.get("comments", 0) or data.get("descendants", 0) or 0
            return float(score + comments)

        if source in ("producthunt_deep", "producthunt"):
            votes = data.get("votes", 0) or 0
            comments = data.get("comments", 0) or 0
            return float(votes * 0.5 + comments)

        # Generic fallback
        return 0.0

    def _quality_multiplier(self, engagement: float) -> float:
        """Map engagement score to quality multiplier."""
        if engagement >= 500:
            return 2.0
        if engagement >= 50:
            return 1.5
        if engagement >= 5:
            return 1.0
        return 0.5

    # ------------------------------------------------------------------
    # Layer 3: Cross-Source
    # ------------------------------------------------------------------

    def _cross_source_multiplier(self, sources: set[str]) -> float:
        """Map number and type of sources to multiplier."""
        has_hn_ph = bool(sources & {"hackernews_comments", "hackernews", "producthunt_deep", "producthunt"})
        count = len(sources)

        if count >= 3:
            return 1.5 if has_hn_ph else 1.3
        if count >= 2:
            return 1.0
        # Single source
        if "twitter_pain" in sources:
            return 0.7
        return 0.7

    def _find_sources_for_pain(self, pain_embedding: list[float], pain_text: str) -> set[str]:
        """Find which sources mention a similar pain via Supabase search."""
        matches = self.chroma.find_similar_pains(
            embedding=pain_embedding,
            threshold=SIMILARITY_THRESHOLD,
            limit=50,
        )
        sources = set()
        for m in matches:
            src = m.get("source", "")
            if src:
                sources.add(src)
        return sources

    # ------------------------------------------------------------------
    # Layer 4: Market Proof
    # ------------------------------------------------------------------

    def find_related_events(self, pain_embedding: list[float], pain_text: str) -> list[dict]:
        """Search for related funding/GitHub/PH/market events.

        Queries both the events table and the funding table.
        """
        related = []

        # Extract keywords
        keywords = [
            w.lower()
            for w in re.findall(r"[a-zA-Z]{4,}", pain_text)
            if w.lower() not in {
                "that", "this", "with", "from", "have", "there",
                "would", "could", "should", "about", "which", "their",
                "when", "what", "your", "they", "been", "some",
                "much", "many", "very", "just", "like", "know",
                "want", "need", "wish", "really", "thing", "make",
            }
        ]

        if not keywords:
            return related

        # Search funding table (Layer 4 - market proof)
        try:
            funding_events = self.funding.search_related_funding(keywords)
            related.extend(funding_events)
        except Exception as e:
            logger.warning("Funding table search failed: %s", e)

        # Search events table for non-funding events (github, producthunt, etc.)
        try:
            for event_type_prefix in ["github", "product"]:
                response = self.dynamo.table.scan(
                    FilterExpression="begins_with(#pk, :prefix)",
                    ExpressionAttributeNames={"#pk": "event_type#first_seen_date"},
                    ExpressionAttributeValues={":prefix": event_type_prefix},
                    Limit=100,
                )
                for item in response.get("Items", []):
                    title = item.get("title", "").lower()
                    overlap = sum(1 for kw in keywords[:8] if kw in title)
                    if overlap >= 1:
                        try:
                            item["data"] = json.loads(item.get("data", "{}"))
                        except (json.JSONDecodeError, TypeError):
                            item["data"] = {}
                        related.append(item)
        except Exception as e:
            logger.warning("DynamoDB scan for related events failed: %s", e)

        return related[:30]

    def calculate_market_bonus(self, related_events: list[dict]) -> int:
        """Calculate Layer 4 market proof bonus.

        Now also considers events from the trendradar-funding table.
        """
        bonus = 0

        for event in related_events:
            source = event.get("source", "")
            data = event.get("data", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = {}

            event_type = event.get("event_type", "")

            # FundBat / VC funding (from either table)
            if source in ("fundbat", "vc_funding") or event_type == "funding_round":
                bonus += 15
                continue

            # YC investment
            if source == "yc" or event_type == "company_founding":
                bonus += 10
                continue

            # GitHub project with stars
            if source in ("github_trending",) or event_type == "github_trending":
                stars = 0
                for key in ("stars", "stargazers_count", "star_count"):
                    val = data.get(key, 0)
                    if isinstance(val, str):
                        val = int(re.sub(r"[^0-9]", "", val) or "0")
                    stars = max(stars, int(val or 0))
                if stars > 1000:
                    bonus += 10
                continue

            # ProductHunt with votes
            if source in ("producthunt", "producthunt_deep") or event_type == "product_launch":
                votes = data.get("votes", 0) or 0
                if isinstance(votes, str):
                    votes = int(re.sub(r"[^0-9]", "", votes) or "0")
                if int(votes) > 100:
                    bonus += 5
                continue

        # Cap the total bonus at 40
        return min(bonus, 40)

    # ------------------------------------------------------------------
    # Main verification
    # ------------------------------------------------------------------

    def verify_pain(self, pain_signal: dict) -> dict:
        """Run four-layer verification on a pain signal.

        Args:
            pain_signal: Dict with at least: title, source, data, embedding.
                         embedding can be a list[float] or None (will generate).

        Returns:
            Dict with: confidence, volume_score, quality_multiplier,
                       cross_source_multiplier, market_bonus, sources,
                       label ("高置信"/"待验证"/"丢弃"), related_events
        """
        pain_text = pain_signal.get("title", "")
        source = pain_signal.get("source", "")
        embedding = pain_signal.get("embedding")

        # Generate embedding if missing
        if not embedding:
            embedding = self.embedding.embed_text(pain_text)

        # Layer 1: Volume
        mention_count = self.count_similar_pains(embedding, pain_text)
        volume_score = self._volume_score(mention_count)

        # Layer 2: Quality
        engagement = self._parse_engagement(pain_signal)
        quality_mult = self._quality_multiplier(engagement)

        # Layer 3: Cross-source
        sources = self._find_sources_for_pain(embedding, pain_text)
        sources.add(source)  # Include the current source
        cross_source_mult = self._cross_source_multiplier(sources)

        # Layer 4: Market proof
        related_events = self.find_related_events(embedding, pain_text)
        market_bonus = self.calculate_market_bonus(related_events)

        # Final confidence
        confidence = min(
            100,
            int(volume_score * quality_mult * cross_source_mult) + market_bonus,
        )

        # Label (threshold lowered to 10 for broad early collection)
        if confidence >= 70:
            label = "高置信"
        elif confidence >= 10:
            label = "待验证"
        else:
            label = "丢弃"

        return {
            "confidence": confidence,
            "volume_score": volume_score,
            "mention_count": mention_count,
            "engagement": engagement,
            "quality_multiplier": quality_mult,
            "cross_source_multiplier": cross_source_mult,
            "sources": sorted(sources),
            "market_bonus": market_bonus,
            "label": label,
            "related_events": related_events,
            "embedding": embedding,
        }
