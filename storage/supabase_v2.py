"""Supabase v2.1 client for pain_signals and opportunity_clusters tables.

Requires pgvector extension and the match_pain_signals RPC function.
See sql/v2.1_schema.sql for setup.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None  # type: ignore
    Client = None  # type: ignore

logger = logging.getLogger(__name__)


class SupabaseV2Client:
    """Client for Supabase v2.1 tables (pain_signals, opportunity_clusters)."""

    def __init__(self) -> None:
        self.url = os.environ.get("SUPABASE_URL")
        self.key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
        if create_client is None:
            raise ImportError("supabase package not installed")
        self._client: Client = create_client(self.url, self.key)

    # ------------------------------------------------------------------
    # pain_signals
    # ------------------------------------------------------------------

    def save_pain_signal(
        self,
        pain_text: str,
        source: str,
        embedding: list[float],
        source_id: Optional[str] = None,
        source_url: Optional[str] = None,
        confidence: int = 0,
        volume_score: int = 0,
        quality_score: float = 0.0,
        cross_source_count: int = 0,
        market_bonus: int = 0,
        cluster_id: Optional[str] = None,
    ) -> dict:
        """Save a pain signal with embedding.

        Args:
            pain_text: The pain/signal text.
            source: Source identifier (e.g., 'reddit', 'hackernews').
            embedding: 2048-dim embedding vector.
            source_id: Optional ID from the source system.
            source_url: Optional URL to the source.
            confidence: Confidence score 0-100.
            volume_score: How frequently this pain appears.
            quality_score: Quality weight.
            cross_source_count: Number of distinct sources mentioning this.
            market_bonus: Bonus for market timing signals.
            cluster_id: Optional cluster this signal belongs to.

        Returns:
            The inserted record.
        """
        record = {
            "pain_text": pain_text,
            "source": source,
            "embedding": embedding,
            "source_id": source_id,
            "source_url": source_url,
            "confidence": confidence,
            "volume_score": volume_score,
            "quality_score": quality_score,
            "cross_source_count": cross_source_count,
            "market_bonus": market_bonus,
        }
        if cluster_id is not None:
            record["cluster_id"] = cluster_id

        result = (
            self._client.table("pain_signals")
            .insert(record)
            .execute()
        )
        if result.data:
            return result.data[0]
        return {}

    def find_similar_pains(
        self,
        embedding: list[float],
        threshold: float = 0.5,
        limit: int = 10,
    ) -> list[dict]:
        """Find pain signals with similar embedding.

        Fetches recent pain_signals with embeddings and computes
        cosine similarity in Python (avoids Supabase RPC issues with vector types).

        Args:
            embedding: Query embedding vector (2048-dim).
            threshold: Minimum cosine similarity (default 0.5).
            limit: Maximum results to return.

        Returns:
            List of matching pain signals with similarity scores.
        """
        import numpy as np

        # Fetch recent pain signals that have embeddings
        try:
            result = (
                self._client.table("pain_signals")
                .select("id, pain_text, source, confidence, embedding")
                .not_.is_("embedding", "null")
                .order("created_at", desc=True)
                .limit(500)
                .execute()
            )
        except Exception:
            return []

        if not result.data:
            return []

        # Compute cosine similarity in Python
        query_vec = np.array(embedding)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        matches = []
        for row in result.data:
            emb = row.get("embedding")
            if not emb:
                continue
            row_vec = np.array(emb)
            row_norm = np.linalg.norm(row_vec)
            if row_norm == 0:
                continue
            similarity = float(np.dot(query_vec, row_vec) / (query_norm * row_norm))
            if similarity >= threshold:
                matches.append({
                    "id": row["id"],
                    "pain_text": row["pain_text"],
                    "source": row["source"],
                    "confidence": row.get("confidence", 0),
                    "similarity": similarity,
                })

        # Sort by similarity descending
        matches.sort(key=lambda x: x["similarity"], reverse=True)
        return matches[:limit]

    # ------------------------------------------------------------------
    # opportunity_clusters
    # ------------------------------------------------------------------

    def save_opportunity_cluster(
        self,
        title: str,
        description: str,
        scores: dict,
        embedding: list[float],
        reasoning: Optional[str] = None,
        related_events: Optional[list[dict]] = None,
        is_actionable: bool = False,
    ) -> dict:
        """Save an opportunity cluster.

        Args:
            title: Cluster title.
            description: Cluster description.
            scores: Dict with pain_score, tech_score, timing_score, total_score, confidence.
            embedding: 2048-dim embedding vector.
            reasoning: AI reasoning for the scores.
            related_events: List of related event references.
            is_actionable: Whether this cluster is actionable.

        Returns:
            The inserted record.
        """
        record = {
            "title": title,
            "description": description,
            "pain_score": scores.get("pain_score", 0),
            "tech_score": scores.get("tech_score", 0),
            "timing_score": scores.get("timing_score", 0),
            "total_score": scores.get("total_score", 0),
            "confidence": scores.get("confidence", 0),
            "is_actionable": is_actionable,
            "reasoning": reasoning,
            "related_events": json.dumps(related_events or []),
            "embedding": embedding,
        }

        result = (
            self._client.table("opportunity_clusters")
            .insert(record)
            .execute()
        )
        if result.data:
            return result.data[0]
        return {}

    def update_user_rating(self, cluster_id: str, rating: int) -> dict:
        """Update user rating (1-10) for an opportunity cluster.

        Args:
            cluster_id: UUID of the cluster.
            rating: User rating 1-10.

        Returns:
            The updated record.
        """
        now = datetime.now(timezone.utc).isoformat()
        result = (
            self._client.table("opportunity_clusters")
            .update({
                "user_rating": rating,
                "updated_at": now,
            })
            .eq("id", cluster_id)
            .execute()
        )
        if result.data:
            return result.data[0]
        return {}
