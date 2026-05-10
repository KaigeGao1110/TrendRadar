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
        category: Optional[str] = None,
    ) -> dict:
        """Save a pain signal with embedding. Skips duplicates (>0.95 similarity)."""
        # Deduplication: check for near-duplicate before inserting
        results = self.pains.query(
            query_embeddings=[embedding],
            n_results=1,
            include=["distances"]
        )
        if results["distances"] and results["distances"][0]:
            # cosine distance < 0.05 means similarity > 0.95
            if results["distances"][0][0] < 0.05:
                return {"id": None, "skipped": True}

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
        if category:
            metadata["category"] = category
        else:
            metadata["category"] = "unknown"

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
        category: Optional[str] = None,
        cross_source_count: int = 0,
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
            "cross_source_count": cross_source_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if category:
            metadata["category"] = category
        else:
            metadata["category"] = "unknown"

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

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------

    SOURCE_TO_CATEGORY = {
        "hackernews_comments": "Developer Tools",
        "twitter_pain": "Other",
        "producthunt_deep": "SaaS",
        "reddit": "Other",
        "rss_pain": "Other",
        "exa_pain": "Other",
    }

    CATEGORIES = [
        "Developer Tools", "AI/ML", "SaaS", "DevOps",
        "Security", "Data", "Fintech", "EdTech", "Health", "Other",
    ]

    def backfill_categories(self, dry_run: bool = True) -> dict:
        """Backfill category for pain_signals and opportunity_clusters.

        Args:
            dry_run: If True, only count what would be updated.

        Returns:
            Dict with counts of updated/skipped.
        """
        import os
        import requests

        results = {"pains_updated": 0, "pains_skipped": 0, "clusters_updated": 0, "clusters_skipped": 0}

        # --- Pain signals: set category from source mapping ---
        # Get all pain signals
        all_pains = self.pains.get(include=["metadatas"])
        if not all_pains.get("ids"):
            logger.info("No pain signals to backfill")
            return results

        pains_to_update = []
        for i, pid in enumerate(all_pains["ids"]):
            meta = all_pains["metadatas"][i]
            cat = meta.get("category", "unknown")
            if cat == "unknown":
                source = meta.get("source", "")
                inferred = self.SOURCE_TO_CATEGORY.get(source, "Other")
                pains_to_update.append((pid, inferred))

        results["pains_skipped"] = len(all_pains["ids"]) - len(pains_to_update)
        if dry_run:
            logger.info("[DRY RUN] Would update %d pain signals with category", len(pains_to_update))
            results["pains_updated"] = len(pains_to_update)
        else:
            # Batch update pain signals
            for pid, inferred_cat in pains_to_update:
                self.pains.update(ids=[pid], metadatas=[{"category": inferred_cat}])
            results["pains_updated"] = len(pains_to_update)
            logger.info("Updated %d pain signals with category", len(pains_to_update))

        # --- Opportunity clusters: LLM classification for unknown categories ---
        all_clusters = self.clusters.get(include=["metadatas", "documents"])
        if not all_clusters.get("ids"):
            logger.info("No clusters to backfill")
            return results

        clusters_to_update = []
        for i, cid in enumerate(all_clusters["ids"]):
            meta = all_clusters["metadatas"][i]
            cat = meta.get("category", "unknown")
            if cat == "unknown":
                doc = all_clusters["documents"][i] or ""
                clusters_to_update.append((cid, doc[:500]))  # first 500 chars for classification

        results["clusters_skipped"] = len(all_clusters["ids"]) - len(clusters_to_update)

        if dry_run:
            logger.info("[DRY RUN] Would classify %d clusters with LLM", len(clusters_to_update))
            results["clusters_updated"] = 0
            return results

        # Classify in batches of 10
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            logger.warning("OPENROUTER_API_KEY not set, skipping cluster classification")
            return results

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        batch_size = 10
        for batch_start in range(0, len(clusters_to_update), batch_size):
            batch = clusters_to_update[batch_start:batch_start + batch_size]

            # Build classification prompt for the batch
            cluster_list = []
            for idx, (cid, doc) in enumerate(batch):
                cluster_list.append(f"{idx + 1}. {doc[:200]}")

            prompt = f"""Classify each opportunity cluster into ONE of these categories:
Developer Tools, AI/ML, SaaS, DevOps, Security, Data, Fintech, EdTech, Health, Other

For each cluster description, choose the most fitting category.

Clusters:
{chr(10).join(cluster_list)}

Respond with ONLY valid JSON, a list of category names in order:
{{"categories": ["Category1", "Category2", ...]}}"""

            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json={"model": "openai/gpt-oss-120b:free", "messages": [{"role": "user", "content": prompt}]},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                import json as json_mod
                parsed = json_mod.loads(content)
                categories = parsed.get("categories", [])
            except Exception as e:
                logger.warning("LLM classification failed for batch: %s", e)
                categories = ["Other"] * len(batch)

            # Update each cluster in this batch
            for j, (cid, _) in enumerate(batch):
                cat = categories[j] if j < len(categories) else "Other"
                self.clusters.update(ids=[cid], metadatas=[{"category": cat}])

            results["clusters_updated"] += len(batch)
            logger.info("Classified batch of %d clusters", len(batch))

        return results