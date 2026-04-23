"""Phase 2: AI-powered analysis pipeline for TrendRadar opportunities.

Fetches unanalyzed events from DynamoDB, deduplicates via vector similarity,
scores each event, classifies opportunity type, and writes results to Supabase.
"""

import os
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from analyzer.scoring import (
    compute_total_score,
    compute_pain_density,
    compute_tech_feasibility,
    compute_timing,
    classify_opportunity_type,
    classify_imitation_difficulty,
)
from analyzer.dedup import find_similar_opportunities, should_merge
from analyzer.reasoning import generate_reasoning, generate_suggested_action


def fetch_unanalyzed_events(dynamodb_table, limit: int = 50) -> list[dict]:
    """Fetch events where is_analyzed != 'true'.

    Args:
        dynamodb_table: boto3 DynamoDB table resource
        limit: Maximum number of events to fetch

    Returns:
        List of event dicts
    """
    response = dynamodb_table.scan(
        FilterExpression="is_analyzed <> :true",
        ProjectionExpression=(
            "event_id, event_type, first_seen_date, title, description, url, "
            "categories, keywords, entities, severity, signal_count, source_ids, embedding"
        ),
        Limit=limit,
    )
    return response.get("Items", [])


def build_event_text(event: dict) -> str:
    """Build text blob from event for embedding and analysis."""
    parts = []
    title = event.get("title", "")
    description = event.get("description", "")
    event_type = event.get("event_type", "")
    categories = event.get("categories", [])
    keywords = event.get("keywords", [])

    if title:
        parts.append(title)
    if description:
        parts.append(description)
    if event_type:
        parts.append(f"type: {event_type}")
    if categories:
        parts.append(f"categories: {', '.join(categories)}")
    if keywords:
        parts.append(f"keywords: {', '.join(keywords)}")
    return " | ".join(parts)


def run_analysis_pipeline(
    dynamodb_table,
    supabase_client,
    openai_client,
    anthropic_client,
    limit: int = 50,
) -> list[dict]:
    """Run the full AI analysis pipeline on unanalyzed events.

    Args:
        dynamodb_table: boto3 DynamoDB table resource
        supabase_client: Supabase client instance
        openai_client: OpenAI client instance
        anthropic_client: Anthropic client instance
        limit: Maximum events to process per run

    Returns:
        List of created/updated opportunity records
    """
    events = fetch_unanalyzed_events(dynamodb_table, limit=limit)
    if not events:
        return []

    opportunities = []
    for event in events:
        event_id = event["event_id"]
        event_text = build_event_text(event)

        # Step 1: Compute embedding
        embedding = _get_or_compute_embedding(openai_client, event_text, event)

        # Step 2: Check for similar existing opportunities (dedup)
        similar = find_similar_opportunities(supabase_client, embedding)
        merged = should_merge(event, similar)

        if merged.get("should_merge") and merged.get("existing_id"):
            # Update existing opportunity
            opp = _update_existing_opportunity(
                supabase_client,
                dynamodb_table,
                event,
                merged["existing_id"],
                embedding,
                openai_client,
                anthropic_client,
            )
            if opp:
                opportunities.append(opp)
        else:
            # Create new opportunity
            opp = _create_new_opportunity(
                supabase_client,
                dynamodb_table,
                event,
                embedding,
                openai_client,
                anthropic_client,
            )
            if opp:
                opportunities.append(opp)

    return opportunities


def _get_or_compute_embedding(openai_client, text: str, event: dict) -> list[float]:
    """Get existing embedding or compute new one via OpenAI."""
    existing = event.get("embedding")
    if existing and len(existing) > 0:
        return existing

    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000],
    )
    return response.data[0].embedding


def _update_existing_opportunity(
    supabase_client,
    dynamodb_table,
    event: dict,
    existing_id: str,
    embedding: list[float],
    openai_client,
    anthropic_client,
) -> Optional[dict]:
    """Update an existing opportunity with new event data."""
    # Re-score to see if score changed
    score_breakdown = {
        "pain_density": compute_pain_density(event),
        "tech_feasibility": compute_tech_feasibility(event),
        "timing": compute_timing(event),
    }
    total_score = compute_total_score(score_breakdown)

    # Only update if score meaningfully changed
    try:
        existing = supabase_client.table("opportunities").select("*").eq("id", existing_id).execute()
        if existing.data:
            old_score = existing.data[0].get("score", 0)
            if abs(total_score - old_score) < 5:
                # Mark event as analyzed, no opportunity update needed
                _mark_event_analyzed(dynamodb_table, event)
                return None
    except Exception:
        pass

    return _create_or_update_opportunity(
        supabase_client,
        dynamodb_table,
        event,
        embedding,
        openai_client,
        anthropic_client,
        existing_id=existing_id,
    )


def _create_new_opportunity(
    supabase_client,
    dynamodb_table,
    event: dict,
    embedding: list[float],
    openai_client,
    anthropic_client,
) -> Optional[dict]:
    """Create a new opportunity from an event."""
    return _create_or_update_opportunity(
        supabase_client,
        dynamodb_table,
        event,
        embedding,
        openai_client,
        anthropic_client,
        existing_id=None,
    )


def _create_or_update_opportunity(
    supabase_client,
    dynamodb_table,
    event: dict,
    embedding: list[float],
    openai_client,
    anthropic_client,
    existing_id: Optional[str] = None,
) -> Optional[dict]:
    """Create or update an opportunity record in Supabase."""
    event_id = event["event_id"]
    event_text = build_event_text(event)

    # Compute score breakdown
    pain_density = compute_pain_density(event)
    tech_feasibility = compute_tech_feasibility(event)
    timing = compute_timing(event)
    score_breakdown = {
        "pain_density": pain_density,
        "tech_feasibility": tech_feasibility,
        "timing": timing,
    }
    total_score = compute_total_score(score_breakdown)

    # Classify opportunity
    opp_type = classify_opportunity_type(event, score_breakdown)
    imitation_diff = classify_imitation_difficulty(event, opp_type, score_breakdown)

    # Extract pain points from keywords/categories/description
    pain_points = _extract_pain_points(event)
    target_market = _extract_target_market(event)
    tech_stack = _extract_tech_stack(event)

    # Generate reasoning and suggested action via LLM
    reasoning = generate_reasoning(anthropic_client, event_text, score_breakdown, opp_type, imitation_diff)
    suggested_action = generate_suggested_action(anthropic_client, event_text, opp_type, imitation_diff, total_score)

    # Build references from source_ids
    references = _build_references(event)

    is_actionable = total_score >= 55

    record = {
        "event_id": event_id,
        "opportunity_type": opp_type,
        "score": total_score,
        "score_breakdown": score_breakdown,
        "imitation_difficulty": imitation_diff,
        "suggested_action": suggested_action,
        "reasoning": reasoning,
        "references": references,
        "is_actionable": is_actionable,
        "status": "new",
        "pain_points": pain_points,
        "target_market": target_market,
        "tech_stack_hint": tech_stack,
        "embedding": embedding,
    }

    try:
        if existing_id:
            result = (
                supabase_client.table("opportunities")
                .update(record)
                .eq("id", existing_id)
                .execute()
            )
        else:
            result = (
                supabase_client.table("opportunities")
                .insert(record)
                .execute()
            )

        if result.data:
            # Mark DynamoDB event as analyzed
            _mark_event_analyzed(dynamodb_table, event)
            return result.data[0]
    except Exception as e:
        print(f"Error saving opportunity: {e}")

    return None


def _mark_event_analyzed(dynamodb_table, event: dict) -> None:
    """Mark an event as analyzed in DynamoDB."""
    try:
        dynamodb_table.update_item(
            Key={
                "PK": f"{event['event_type']}#{event['first_seen_date']}",
                "SK": event["event_id"],
            },
            UpdateExpression="SET is_analyzed = :true",
            ExpressionAttributeValues={":true": "true"},
        )
    except Exception as e:
        print(f"Error marking event analyzed: {e}")


def _extract_pain_points(event: dict) -> list[str]:
    """Extract pain points from event keywords and description."""
    pain_points = []
    keywords = event.get("keywords", [])
    description = event.get("description", "") or ""

    if isinstance(keywords, list):
        for kw in keywords:
            if kw and len(kw) < 100:
                pain_points.append(kw)

    if description and len(pain_points) < 3:
        pain_points.append(description[:200])

    return pain_points[:5]


def _extract_target_market(event: dict) -> str:
    """Extract target market from categories."""
    categories = event.get("categories", [])
    if isinstance(categories, list) and categories:
        return categories[0]
    return "General"


def _extract_tech_stack(event: dict) -> list[str]:
    """Extract tech stack hints from keywords."""
    keywords = event.get("keywords", [])
    tech_keywords = ["python", "javascript", "typescript", "react", "nextjs", "node",
                     "go", "rust", "postgres", "supabase", "aws", "openai", "ai",
                     "llm", "api", "saas", "cloud"]
    if isinstance(keywords, list):
        found = [kw for kw in keywords if any(t in kw.lower() for t in tech_keywords)]
        return found[:5]
    return []


def _build_references(event: dict) -> list[dict]:
    """Build references list from event source_ids."""
    references = []
    source_ids = event.get("source_ids", [])
    title = event.get("title", "")
    url = event.get("url", "")

    if url:
        references.append({
            "source": "event",
            "url": url,
            "snippet": title[:200] if title else "",
        })

    if isinstance(source_ids, list):
        for sid in source_ids[:5]:
            references.append({
                "source": sid,
                "url": "",
                "snippet": sid,
            })

    return references
