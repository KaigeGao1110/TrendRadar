"""ChromaDB client for pain_signals and opportunity_clusters collections.

Replaces SupabaseV2Client for local-only operation.
"""

import chromadb
from chromadb.config import Settings
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)

CHROMA_PATH = "/home/kaige/Projects/TrendRadar/data/chroma"


class ChromaClient:
    """ChromaDB client for pain signals and opportunity clusters."""

    def __init__(self, path: str = CHROMA_PATH):
        self.client = chromadb.PersistentClient(path=path)

        # Pain signals collection
        self.pains = self.client.get_or_create_collection(
            name="pain_signals",
            metadata={"hnsw:space": "cosine"}
        )

        # Opportunity clusters collection
        self.clusters = self.client.get_or_create_collection(
            name="opportunity_clusters",
            metadata={"hnsw:space": "cosine"}
        )

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
        """Save a pain signal with embedding."""
        import uuid
        signal_id = str(uuid.uuid4())

        metadata = {
            "source": source,
            "confidence": confidence,
            "volume_score": volume_score,
            "quality_score": quality_score,
            "cross_source_count": cross_source_count,
            "market_bonus": market_bonus,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if source_id:
            metadata["source_id"] = source_id
        if source_url:
            metadata["source_url"] = source_url
        if cluster_id:
            metadata["cluster_id"] = cluster_id

        self.pains.add(
            ids=[signal_id],
            embeddings=[embedding],
            documents=[pain_text],
            metadatas=[metadata]
        )

        return {"id": signal_id, **metadata}

    def find_similar_pains(
        self,
        embedding: list[float],
        threshold: float = 0.5,
        limit: int = 10,
    ) -> list[dict]:
        """Find pain signals with similar embedding using ChromaDB query."""
        # ChromaDB returns cosine distance, convert to similarity
        # distance = 1 - similarity, so similarity = 1 - distance
        results = self.pains.query(
            query_embeddings=[embedding],
            n_results=min(limit * 2, 100),  # Fetch more to filter by threshold
            include=["metadatas", "documents", "distances"]
        )

        matches = []
        if not results["ids"][0]:
            return matches

        for i, signal_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            similarity = 1 - distance  # Convert distance to similarity

            if similarity >= threshold:
                matches.append({
                    "id": signal_id,
                    "pain_text": results["documents"][0][i],
                    "source": results["metadatas"][0][i].get("source", ""),
                    "confidence": results["metadatas"][0][i].get("confidence", 0),
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
        """Save an opportunity cluster."""
        import uuid
        import json
        cluster_id = str(uuid.uuid4())

        metadata = {
            "pain_score": scores.get("pain_score", 0),
            "tech_score": scores.get("tech_score", 0),
            "timing_score": scores.get("timing_score", 0),
            "total_score": scores.get("total_score", 0),
            "confidence": scores.get("confidence", 0),
            "is_actionable": is_actionable,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Store reasoning and related_events in document text
        doc = f"{title}\n\n{description}"
        if reasoning:
            doc += f"\n\nReasoning: {reasoning}"

        self.clusters.add(
            ids=[cluster_id],
            embeddings=[embedding],
            documents=[doc],
            metadatas=[metadata]
        )

        return {"id": cluster_id, **metadata}

    def update_user_rating(self, cluster_id: str, rating: int) -> dict:
        """Update user rating (1-10) for an opportunity cluster."""
        # ChromaDB doesn't support update metadata directly
        # Would need to delete and re-add, skip for now
        logger.warning("update_user_rating not implemented for ChromaDB")
        return {}