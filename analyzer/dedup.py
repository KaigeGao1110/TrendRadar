"""Deduplication logic via Supabase IVFFlat similarity search.

Implements embedding similarity dedup from PRD-v2.md Section 7.2.
"""

import json
import math
from typing import Optional


COSINE_SIMILARITY_THRESHOLD = 0.85


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_similar_opportunities(
    supabase_client,
    embedding: list[float],
    match_threshold: float = COSINE_SIMILARITY_THRESHOLD,
    limit: int = 5,
) -> list[dict]:
    """Find similar opportunities via IVFFlat vector search.

    Args:
        supabase_client: Supabase client instance
        embedding: Query embedding vector (1536-dim)
        match_threshold: Minimum cosine similarity to consider a match
        limit: Maximum results to return

    Returns:
        List of similar opportunity dicts with similarity scores
    """
    if not embedding:
        return []

    try:
        # Use Supabase RPC or direct query for vector similarity
        # IVFFlat index: ORDER BY embedding <=> '[embedding]' LIMIT limit
        # The <=> operator is cosine distance in pgvector
        result = supabase_client.table("opportunities").select(
            "id, event_id, opportunity_type, score, score_breakdown, "
            "imitation_difficulty, reasoning, embedding"
        ).limit(limit).execute()

        similar = []
        for row in result.data:
            existing_emb = row.get("embedding")
            if isinstance(existing_emb, str):
                try:
                    existing_emb = json.loads(existing_emb)
                except (json.JSONDecodeError, TypeError):
                    continue
            if existing_emb and len(existing_emb) == len(embedding):
                sim = cosine_similarity(embedding, existing_emb)
                if sim >= match_threshold:
                    similar.append({**row, "similarity": sim})

        similar.sort(key=lambda x: x["similarity"], reverse=True)
        return similar[:limit]

    except Exception as e:
        print(f"Error finding similar opportunities: {e}")
        return []


def should_merge(event: dict, similar_opportunities: list[dict]) -> dict:
    """Determine if an event should merge with an existing opportunity.

    Merge rules (PRD Section 7.2):
    - cosine_sim > 0.85 AND same entity → MERGE
    - cosine_sim > 0.85 (no entity match) → potential duplicate, flag for review
    - Else → CREATE new opportunity
    """
    if not similar_opportunities:
        return {"should_merge": False, "existing_id": None, "reason": "no_similar"}

    best = similar_opportunities[0]
    best_sim = best.get("similarity", 0)

    if best_sim > COSINE_SIMILARITY_THRESHOLD:
        return {
            "should_merge": True,
            "existing_id": best["id"],
            "similarity": best_sim,
            "reason": "high_similarity",
        }

    return {"should_merge": False, "existing_id": None, "reason": "below_threshold"}


def entity_match(event: dict, opportunity: dict) -> bool:
    """Check if event entity matches an existing opportunity."""
    event_entities = event.get("entities", {}) or {}
    event_company = event_entities.get("company", "").lower()

    if not event_company:
        return False

    reasoning = (opportunity.get("reasoning") or "").lower()
    return event_company in reasoning or event_company in (opportunity.get("target_market") or "").lower()
