"""Semantic clustering engine for TrendRadar v2.1.

Groups events around high-confidence pain signals to form opportunity clusters.
Uses embedding similarity for cross-source semantic matching.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

from storage.embedding import EmbeddingClient
from storage.chroma_client import ChromaClient
from storage.dynamo import DynamoClient, FundingClient
from analyzer.pain_verifier import PainVerifier, PAIN_SOURCES, cosine_similarity
from analyzer.scorer import score_event, _get_client, SCORING_MODEL, _parse_scoring_json

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.5
RATE_LIMIT_INTERVAL = 0.35


class ClusterEngine:
    """Semantic clustering engine — groups events around pain signals."""

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        chroma: ChromaClient,
        dynamo: DynamoClient,
        pain_verifier: PainVerifier,
    ):
        self.embedding = embedding_client
        self.chroma = chroma
        self.dynamo = dynamo
        self.verifier = pain_verifier

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def process_daily_signals(self, date: Optional[str] = None) -> list[dict]:
        """Process all signals for a day: embed → cluster → verify → score → save.

        Args:
            date: YYYY-MM-DD string (default: today UTC).

        Returns:
            List of opportunity cluster dicts.
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        logger.info("Processing daily signals for %s", date)

        # 1. Fetch unanalyzed events from DynamoDB
        events = self.dynamo.get_unanalyzed_events(limit=200)
        if not events:
            logger.info("No unanalyzed events found")
            return []

        logger.info("Found %d unanalyzed events", len(events))

        # 2. Generate embeddings for events that lack them
        events = self._ensure_embeddings(events)

        # 3. Separate pain signals from other events
        pain_events = [e for e in events if e.get("source") in PAIN_SOURCES]
        other_events = [e for e in events if e.get("source") not in PAIN_SOURCES]

        logger.info("Pain signals: %d, Other events: %d", len(pain_events), len(other_events))

        if not pain_events:
            # No pain signals — still cluster around the most interesting events
            # Use all events but with lower priority
            logger.info("No pain signals found; clustering around top-scored events")
            pain_events = events[:5]  # Use top 5 as pseudo-pains

        # 4. Verify pain signals
        verified_pains = []
        for pain in pain_events:
            try:
                result = self.verifier.verify_pain(pain)
                pain["verification"] = result
                verified_pains.append(pain)
            except Exception as e:
                logger.warning("Failed to verify pain '%s': %s", pain.get("title", "")[:50], e)

        # Filter out discarded pains (confidence < 50)
        actionable_pains = [
            p for p in verified_pains
            if p["verification"]["label"] != "丢弃"
        ]
        logger.info(
            "Verified pains: %d total, %d actionable (not discarded)",
            len(verified_pains), len(actionable_pains),
        )

        # 5. Deduplicate pains by semantic similarity
        unique_pains = self._deduplicate_pains(actionable_pains)
        logger.info("Unique pain clusters: %d", len(unique_pains))

        # 6. Cluster around each unique pain
        clusters = []
        for pain in unique_pains:
            try:
                cluster = self.cluster_around_pain(pain, other_events)
                if cluster:
                    # 7. Score the cluster
                    scored = self.score_cluster(cluster)
                    clusters.append(scored)
            except Exception as e:
                logger.warning("Failed to cluster around pain: %s", e)

        # Sort by total_score descending
        clusters.sort(key=lambda c: c.get("total_score", 0), reverse=True)

        # 8. Save verified pain signals to ChromaDB for cross-day dedup
        for pain in actionable_pains:
            try:
                v = pain.get("verification", {})
                emb = v.get("embedding") or pain.get("embedding")
                if emb and pain.get("title"):
                    self.chroma.save_pain_signal(
                        pain_text=pain.get("title", ""),
                        source=pain.get("source", ""),
                        embedding=emb,
                        confidence=v.get("confidence", 0),
                        volume_score=v.get("volume_score", 0),
                        quality_score=v.get("quality_multiplier", 0),
                        cross_source_count=len(v.get("sources", [])),
                        market_bonus=v.get("market_bonus", 0),
                    )
            except Exception as e:
                logger.warning("Failed to save pain signal: %s", e)

        # 9. Save clusters to ChromaDB
        for cluster in clusters:
            try:
                self._save_cluster(cluster)
            except Exception as e:
                logger.warning("Failed to save cluster '%s': %s", cluster.get("title", ""), e)

        logger.info("Generated %d opportunity clusters", len(clusters))

        # 10. Mark all processed events as analyzed
        self._mark_events_analyzed(events)

        return clusters

    def _mark_events_analyzed(self, events: list[dict], score: Optional[int] = None) -> None:
        """Mark processed events as analyzed in DynamoDB.

        Uses the event_id-index GSI to look up each event's PK and update it.
        """
        for event in events:
            event_id = event.get("event_id", "")
            if not event_id:
                continue
            try:
                # Compute total score for this event if not provided
                event_score = score
                if event_score is None:
                    verification = event.get("verification", {})
                    conf = verification.get("confidence", 0)
                    # Use confidence as a proxy for event score
                    event_score = conf if conf > 0 else None
                self.dynamo.mark_analyzed(event_id, score=event_score)
            except Exception as e:
                logger.warning("Failed to mark event analyzed: %s", e)

    # ------------------------------------------------------------------
    # Embedding generation
    # ------------------------------------------------------------------

    def _ensure_embeddings(self, events: list[dict]) -> list[dict]:
        """Ensure all events have embeddings. Generate missing ones."""
        for event in events:
            if event.get("embedding"):
                continue
            if event.get("embedding_generated") == "true":
                continue

            text = event.get("title", "")
            if not text:
                continue

            try:
                event["embedding"] = self.embedding.embed_text(text)
                event["embedding_generated"] = True
            except Exception as e:
                logger.warning("Embedding failed for '%s': %s", text[:50], e)
                event["embedding"] = None

        return events

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _deduplicate_pains(self, pains: list[dict]) -> list[dict]:
        """Merge semantically similar pains, keeping the highest-confidence one."""
        if not pains:
            return []

        merged = []
        used = set()

        for i, pain in enumerate(pains):
            if i in used:
                continue
            emb_i = pain.get("embedding") or pain.get("verification", {}).get("embedding")
            if not emb_i:
                merged.append(pain)
                continue

            group = [pain]
            for j in range(i + 1, len(pains)):
                if j in used:
                    continue
                emb_j = pains[j].get("embedding") or pains[j].get("verification", {}).get("embedding")
                if not emb_j:
                    continue
                sim = cosine_similarity(emb_i, emb_j)
                if sim > SIMILARITY_THRESHOLD:
                    group.append(pains[j])
                    used.add(j)

            # Keep the highest-confidence pain as representative
            best = max(group, key=lambda p: p.get("verification", {}).get("confidence", 0))
            # Merge mention counts
            total_mentions = sum(
                p.get("verification", {}).get("mention_count", 1) for p in group
            )
            best["verification"]["mention_count"] = total_mentions
            best["_group_size"] = len(group)
            merged.append(best)
            used.add(i)

        return merged

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def cluster_around_pain(self, pain: dict, all_events: list[dict]) -> Optional[dict]:
        """Form a cluster around a pain signal by finding related events.

        Args:
            pain: Verified pain signal dict with verification results.
            all_events: Other events to search for related signals.

        Returns:
            Cluster dict or None if no meaningful cluster can be formed.
        """
        pain_emb = pain.get("embedding") or pain.get("verification", {}).get("embedding")
        if not pain_emb:
            return None

        pain_text = pain.get("title", "")
        verification = pain.get("verification", {})

        # Find related events by embedding similarity
        layer1 = [pain]  # Pain signals
        layer2 = []  # Tech events
        layer3 = []  # Market events

        for event in all_events:
            emb = event.get("embedding")
            if not emb:
                continue

            sim = cosine_similarity(pain_emb, emb)
            if sim < SIMILARITY_THRESHOLD:
                continue

            source = event.get("source", "")
            if source in ("github_trending", "hackernews", "hackernews_comments"):
                layer2.append(event)
            elif source in ("fundbat", "vc_funding", "newsapi", "rss", "yc", "google_trends"):
                layer3.append(event)
            elif source in PAIN_SOURCES:
                layer1.append(event)
            else:
                layer2.append(event)  # Default to tech layer

        # Also add related events from verification
        related = verification.get("related_events", [])
        for ev in related:
            source = ev.get("source", "")
            ev_type = ev.get("event_type", "")
            if source in ("fundbat", "vc_funding") or ev_type == "funding_round":
                if ev not in layer3:
                    layer3.append(ev)
            elif source == "yc" or ev_type == "company_founding":
                if ev not in layer3:
                    layer3.append(ev)

        # Generate cluster title and description
        title = pain_text[:80] if pain_text else "Untitled Opportunity"
        description = self._generate_description(pain, layer1, layer2, layer3)

        # Build source summary
        all_sources = set()
        for ev in layer1 + layer2 + layer3:
            src = ev.get("source", "")
            if src:
                all_sources.add(src)

        return {
            "title": title,
            "description": description,
            "pain_event": pain,
            "layer1": layer1,
            "layer2": layer2,
            "layer3": layer3,
            "confidence": verification.get("confidence", 0),
            "sources": sorted(all_sources),
            "pain_text": pain_text,
            "embedding": pain_emb,
            "verification": verification,
        }

    def _generate_description(
        self, pain: dict, layer1: list, layer2: list, layer3: list
    ) -> str:
        """Generate a brief cluster description."""
        parts = []

        if layer1:
            parts.append(f"Pain signals: {len(layer1)}")
        if layer2:
            parts.append(f"Tech signals: {len(layer2)}")
        if layer3:
            parts.append(f"Market signals: {len(layer3)}")

        desc = pain.get("title", "")
        if parts:
            desc += f" ({', '.join(parts)})"

        return desc

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_cluster(self, cluster: dict) -> dict:
        """Score an opportunity cluster using AI.

        Uses the scoring model from scorer.py but
        evaluates the cluster as a whole across three dimensions.

        Args:
            cluster: Cluster dict from cluster_around_pain.

        Returns:
            Updated cluster with scores.
        """
        verification = cluster.get("verification", {})
        confidence = verification.get("confidence", 0)

        # Build a rich prompt for the scoring model
        pain_text = cluster.get("pain_text", "")
        layer1_titles = [e.get("title", "") for e in cluster.get("layer1", [])]
        layer2_titles = [e.get("title", "") for e in cluster.get("layer2", [])]
        layer3_titles = [e.get("title", "") for e in cluster.get("layer3", [])]

        prompt = f"""Analyze this startup opportunity cluster and score it:

**Core Pain Signal (confidence: {confidence}/100):**
{pain_text}

**Related Pain Signals:**
{chr(10).join(f'- {t}' for t in layer1_titles[:5]) or 'None'}

**Tech/Implementation Signals:**
{chr(10).join(f'- {t}' for t in layer2_titles[:5]) or 'None'}

**Market/Validation Signals:**
{chr(10).join(f'- {t}' for t in layer3_titles[:5]) or 'None'}

Score on three dimensions (0-100):
1. pain_density: How painful is the core problem?
2. tech_feasibility: Can it be built with current AI tools?
3. timing: Is now the right time to enter?

IMPORTANT: You MUST respond with ONLY valid JSON, no other text, no markdown, no explanation outside JSON. Do not wrap in code fences.
{{"pain_density": <int>, "tech_feasibility": <int>, "timing": <int>, "reasoning": "<1 sentence>"}}"""

        pain_score = 50
        tech_score = 50
        timing_score = 50
        reasoning = ""

        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=SCORING_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert startup opportunity analyst. Score precisely.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=3000,
            )


            raw = response.choices[0].message.content.strip()

            result = _parse_scoring_json(raw)
            if result is None:
                logger.warning("Failed to parse cluster scoring response: %s", raw[:200])
                raise ValueError("Unparseable scoring response")

            for key in ("pain_density", "tech_feasibility", "timing"):
                val = result.get(key, 50)
                if not isinstance(val, (int, float)) or val < 0:
                    val = 50
                elif val <= 10:
                    val = int(val * 10)
                elif val > 100:
                    val = 100
                if key == "pain_density":
                    pain_score = int(val)
                elif key == "tech_feasibility":
                    tech_score = int(val)
                else:
                    timing_score = int(val)

            reasoning = result.get("reasoning", "")

        except Exception as e:
            logger.warning("AI scoring failed for cluster, using defaults: %s", e)

        # Weighted total
        total_score = round(
            pain_score * 0.55 + tech_score * 0.30 + timing_score * 0.15
        )

        # Adjust pain score by confidence
        if confidence >= 70:
            total_score = min(100, total_score + 5)
        elif confidence < 50:
            total_score = max(0, total_score - 10)

        cluster["pain_score"] = max(pain_score, 10) if pain_score > 0 else 50
        cluster["tech_score"] = max(tech_score, 10) if tech_score > 0 else 50
        cluster["timing_score"] = max(timing_score, 10) if timing_score > 0 else 50
        cluster["total_score"] = max(total_score, 5) if total_score > 0 else 50
        cluster["reasoning"] = reasoning
        cluster["is_actionable"] = total_score >= 70

        return cluster

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_cluster(self, cluster: dict) -> dict:
        """Save a scored cluster to Supabase."""
        # Build related events list
        related = []
        for ev in cluster.get("layer1", []) + cluster.get("layer2", []) + cluster.get("layer3", []):
            related.append({
                "source": ev.get("source", ""),
                "event_id": ev.get("event_id", ""),
                "title": ev.get("title", ""),
                "url": ev.get("url", ""),
            })

        scores = {
            "pain_score": cluster.get("pain_score", 0),
            "tech_score": cluster.get("tech_score", 0),
            "timing_score": cluster.get("timing_score", 0),
            "total_score": cluster.get("total_score", 0),
            "confidence": cluster.get("confidence", 0),
        }

        record = self.chroma.save_opportunity_cluster(
            title=cluster.get("title", "Untitled"),
            description=cluster.get("description", ""),
            scores=scores,
            embedding=cluster.get("embedding", []),
            reasoning=cluster.get("reasoning", ""),
            related_events=related,
            is_actionable=cluster.get("is_actionable", False),
        )

        cluster["cluster_id"] = record.get("id", "")
        return record
