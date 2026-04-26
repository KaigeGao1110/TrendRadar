"""AI-powered scoring system for TrendRadar opportunities.

Uses OpenAI gpt-4o-mini to evaluate events across three dimensions:
- pain_density (55%): How painful is the problem?
- tech_feasibility (30%): How feasible to replicate with current AI toolchain?
- timing (15%): Is now the right time to enter?

Events scoring >= 70 are marked as actionable.
"""

import json
import logging
import os
import re
import time
import traceback
from datetime import datetime, timezone

from openai import OpenAI

from storage.dynamo import DynamoClient
from storage.dlq import DLQClient

logger = logging.getLogger(__name__)

# Scoring weights
WEIGHTS = {
    "pain_density": 0.55,
    "tech_feasibility": 0.30,
    "timing": 0.15,
}

ACTIONABLE_THRESHOLD = 70
BATCH_SIZE = 20
RATE_LIMIT_INTERVAL = 0.35  # ~3 requests/sec max


def _get_client() -> OpenAI:
    """Get OpenAI-compatible client pointing to local Ollama."""
    return OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama",  # Ollama doesn't need a real key
    )


SCORING_MODEL = "gemma4:31b"


SCORING_SYSTEM_PROMPT = """You are an expert startup opportunity analyst. Score each event on three dimensions:

1. **pain_density (0-100)**: How painful is the problem this opportunity addresses?
   - 80-100: Widespread, acute pain with clear willingness to pay
   - 60-79: Real pain, but limited audience or moderate urgency
   - 40-59: Nice-to-have, inconvenience rather than pain
   - 0-39: Vague or negligible pain

2. **tech_feasibility (0-100)**: How feasible is it to build this with current AI tools?
   - 80-100: Can be built with LLM APIs, no-code tools, or simple integrations in weeks
   - 60-79: Requires some custom development but no deep ML research
   - 40-59: Needs moderate technical complexity, custom models, or domain expertise
   - 0-39: Requires significant R&D, infrastructure, or specialized hardware

3. **timing (0-100)**: Is now the right time to enter this market?
   - 80-100: Market just validated (recent funding, product launches) but not yet saturated
   - 60-79: Growing market with room for new entrants
   - 40-59: Market exists but competitive or early-stage
   - 0-39: Too early (no demand signals) or too late (dominated by incumbents)

IMPORTANT: You MUST respond with ONLY valid JSON, no other text, no markdown, no explanation outside JSON. Do not wrap in code fences.
{"pain_density": <int>, "tech_feasibility": <int>, "timing": <int>, "reasoning": "<2-3 sentence explanation>"}"""


def _build_user_prompt(event: dict) -> str:
    """Build the scoring prompt for a single event."""
    title = event.get("title", "Unknown")
    source = event.get("source", "unknown")
    event_type = event.get("event_type", "unknown")
    url = event.get("url", "")
    
    data = event.get("data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            data = {}
    
    # Extract key fields with fallbacks for different source schemas
    description = (data.get("description", "") or data.get("one_liner", "") 
                   or data.get("tagline", "") or data.get("summary", "") or "")
    industry = data.get("industry", "") or data.get("category", "") or ""
    if isinstance(industry, list):
        industry = ", ".join(industry)
    
    # Include ALL source data as JSON for full context
    data_json = json.dumps(data, ensure_ascii=False, indent=2) if data else "{}"
    
    prompt = f"""Event to score:
Title: {title}
Source: {source}
Type: {event_type}
URL: {url}
Description: {description}
Industry: {industry}

Full source data:
{data_json}"""
    
    return prompt


def _parse_scoring_json(raw: str) -> dict | None:
    """Parse scoring JSON from model output with three-layer fallback.

    Layer 1: strict JSON parse
    Layer 2: regex extract JSON containing "pain_density"
    Layer 3: keyword fallback (extract numbers from plain text)
    """
    if not raw:
        return None

    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Layer 1: strict JSON
    try:
        result = json.loads(text)
        if isinstance(result, dict) and ("pain_density" in result or "tech_feasibility" in result):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Layer 2: regex extract JSON with pain_density
    json_match = re.search(r'\{[^{}]*"pain_density"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # Looser match: try any JSON object with scoring keys
    json_match2 = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if json_match2:
        try:
            result = json.loads(json_match2.group())
            if isinstance(result, dict) and any(k in result for k in ("pain_density", "tech_feasibility", "timing")):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # Layer 3: keyword fallback — extract numbers from plain text
    scores = {}
    for key in ("pain_density", "tech_feasibility", "timing"):
        # Match patterns like "pain_density: 80", "pain_density:80", "pain density: 8/10"
        m = re.search(
            key.replace("_", r'[\s_]+') + r'\s*[:=]\s*(\d+)(?:\s*/\s*\d+)?',
            text, re.IGNORECASE
        )
        if m:
            scores[key] = int(m.group(1))

    if scores:
        # Fill missing keys with default
        for key in ("pain_density", "tech_feasibility", "timing"):
            scores.setdefault(key, 50)
        # Try to extract reasoning from text
        reasoning_match = re.search(r'reasoning\s*[:=]\s*["\']?(.+?)(?:["\']|$)', text, re.IGNORECASE)
        scores["reasoning"] = reasoning_match.group(1).strip() if reasoning_match else "keyword_fallback"
        logger.info("Used keyword fallback, extracted scores: %s", scores)
        return scores

    return None


def score_event(client: OpenAI, event: dict) -> dict | None:
    """Score a single event using local Ollama model.

    Args:
        client: OpenAI-compatible client
        event: Event dict from DynamoDB

    Returns:
        Score dict with pain_density, tech_feasibility, timing, total_score, reasoning
        or None if scoring failed.
    """
    prompt = _build_user_prompt(event)

    try:
        response = client.chat.completions.create(
            model=SCORING_MODEL,
            messages=[
                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
        )
        
        raw = response.choices[0].message.content.strip()
        
        # gemma4 thinking model may put all output in reasoning field
        if not raw:
            reasoning_field = getattr(response.choices[0].message, 'reasoning', '') or ''
            if reasoning_field:
                raw = reasoning_field
        
        result = _parse_scoring_json(raw)
        if result is None:
            logger.warning("Failed to parse scoring response: %s", raw[:200])
            return None
        
        # Validate scores and normalize 0-10 range to 0-100
        for key in ("pain_density", "tech_feasibility", "timing"):
            val = result.get(key, 0)
            if not isinstance(val, (int, float)) or val < 0:
                result[key] = 50
            elif val <= 10:
                result[key] = int(val * 10)  # 0-10 → 0-100
            elif val > 100:
                result[key] = 100
        
        # Compute total
        result["total_score"] = round(
            result["pain_density"] * WEIGHTS["pain_density"]
            + result["tech_feasibility"] * WEIGHTS["tech_feasibility"]
            + result["timing"] * WEIGHTS["timing"]
        )
        
        return result
        
    except Exception as e:
        logger.warning("Scoring failed with exception: %s", e)
        return None


def run_scoring(limit: int = 100) -> dict:
    """Run AI scoring on all unanalyzed events.
    
    Args:
        limit: Max events to process in one run
    
    Returns:
        Summary dict with counts
    """
    dynamo = DynamoClient()
    dlq = DLQClient()
    client = _get_client()
    
    # Fetch unanalyzed events
    events = dynamo.get_unanalyzed_events(limit=limit)
    if not events:
        return {"total": 0, "scored": 0, "failed": 0, "actionable": 0}
    
    scored_count = 0
    failed_count = 0
    actionable_count = 0
    
    for i, event in enumerate(events):
        # Rate limiting
        if i > 0:
            time.sleep(RATE_LIMIT_INTERVAL)
        
        event_id = event.get("event_id", "")
        
        try:
            result = score_event(client, event)
            
            if result is None:
                failed_count += 1
                dlq.add_failure(
                    task_type="ai_scoring",
                    payload={"event_id": event_id, "title": event.get("title", "")},
                    error="OpenAI returned unparseable response",
                    traceback="",
                )
                continue
            
            total_score = result["total_score"]
            is_actionable = total_score >= ACTIONABLE_THRESHOLD
            
            if is_actionable:
                actionable_count += 1
            
            # Update DynamoDB
            _update_scored_event(dynamo, event, result, is_actionable)
            scored_count += 1
            
        except Exception as e:
            failed_count += 1
            dlq.add_failure(
                task_type="ai_scoring",
                payload={"event_id": event_id, "title": event.get("title", "")},
                error=str(e),
                traceback=traceback.format_exc(),
            )
    
    return {
        "total": len(events),
        "scored": scored_count,
        "failed": failed_count,
        "actionable": actionable_count,
    }


def _update_scored_event(
    dynamo: DynamoClient,
    event: dict,
    score_result: dict,
    is_actionable: bool,
) -> None:
    """Update a scored event in DynamoDB.
    
    Updates: is_analyzed, score, score_breakdown, is_actionable, last_updated_at
    """
    event_id = event.get("event_id", "")
    
    # Get the PK from the event (it was stored when fetched)
    # The save_event uses "event_type#first_seen_date" as the PK attribute
    pk = event.get("event_type#first_seen_date", "")
    
    if not pk or not event_id:
        return
    
    now = datetime.now(timezone.utc).isoformat()
    
    score_breakdown = json.dumps({
        "pain_density": score_result["pain_density"],
        "tech_feasibility": score_result["tech_feasibility"],
        "timing": score_result["timing"],
        "reasoning": score_result.get("reasoning", ""),
    })
    
    update_expr = (
        "SET is_analyzed = :analyzed, "
        "#score = :score, "
        "score_breakdown = :breakdown, "
        "is_actionable = :actionable, "
        "last_updated_at = :now"
    )
    expr_attrs = {
        ":analyzed": "true",
        ":score": score_result["total_score"],
        ":breakdown": score_breakdown,
        ":actionable": "true" if is_actionable else "false",
        ":now": now,
    }
    expr_attr_names = {
        "#score": "score",  # 'score' may be a reserved word
    }
    
    try:
        dynamo.table.update_item(
            Key={
                "event_type#first_seen_date": pk,
                "event_id": event_id,
            },
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_attrs,
            ExpressionAttributeNames=expr_attr_names,
        )
    except Exception as e:
        # Fallback: try mark_analyzed which uses a different key lookup
        raise e
