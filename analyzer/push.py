"""Daily push notification generation for TrendRadar.

Generates formatted daily summaries of high-value opportunities.
Output goes to stdout (OpenClaw cron will deliver to Telegram).
Also saves to Supabase digests table for historical tracking.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from storage.dynamo import DynamoClient
from analyzer.cron import get_supabase_client


def get_actionable_events_today(min_score: int = 70, limit: int = 50) -> list[dict]:
    """Fetch actionable events from today.
    
    Args:
        min_score: Minimum score threshold (default 70)
        limit: Maximum events to return
    
    Returns:
        List of actionable events sorted by score descending
    """
    dynamo = DynamoClient()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return dynamo.get_actionable_events(min_score=min_score, date=today, limit=limit)


def format_event_summary(event: dict) -> str:
    """Format a single event for push notification.
    
    Args:
        event: Event dict with score_breakdown
    
    Returns:
        Formatted string
    """
    title = event.get("title", "Unknown")
    score = event.get("score", 0)
    
    # Parse score breakdown
    breakdown_raw = event.get("score_breakdown", "{}")
    if isinstance(breakdown_raw, str):
        try:
            breakdown = json.loads(breakdown_raw)
        except json.JSONDecodeError:
            breakdown = {}
    else:
        breakdown = breakdown_raw
    
    reasoning = breakdown.get("reasoning", "")
    pain = breakdown.get("pain_density", "?")
    feas = breakdown.get("tech_feasibility", "?")
    timing = breakdown.get("timing", "?")
    
    source = event.get("source", "")
    url = event.get("url", "")
    
    # Format the reasoning (truncate if too long)
    if len(reasoning) > 200:
        reasoning = reasoning[:197] + "..."
    
    return f"""**[{score}分]** {title}
   痛点: {pain}/100 | 可行性: {feas}/100 | 时机: {timing}/100
   {reasoning}
   来源: {source} {f"| [链接]({url})" if url else ""}"""


def generate_daily_push(min_score: int = 70, limit: int = 10) -> str:
    """Generate daily push summary of actionable opportunities.
    
    Args:
        min_score: Minimum score threshold (default 70)
        limit: Maximum events to include (default 10)
    
    Returns:
        Formatted markdown string for push notification
    """
    events = get_actionable_events_today(min_score=min_score, limit=limit)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    if not events:
        return f"""🎯 **TrendRadar 每日信号** — {today}

📊 今日暂无高价值机会 (score ≥ {min_score})
继续监控市场动态..."""
    
    # Build the message
    lines = [
        f"🎯 **TrendRadar 每日信号** — {today}",
        "",
        f"🔥 **高价值机会** (score ≥ {min_score}):",
        "",
    ]
    
    for i, event in enumerate(events, 1):
        summary = format_event_summary(event)
        lines.append(f"{i}. {summary}")
        lines.append("")
    
    # Add stats footer
    stats = f"\n📊 **今日统计**: 已识别 {len(events)} 条高价值信号"
    lines.append(stats)
    
    message = "\n".join(lines)
    
    # Save to Supabase digests table (optional, non-blocking)
    try:
        save_digest_to_supabase(today, events, message)
    except Exception:
        pass  # Don't fail push if Supabase save fails
    
    return message


def save_digest_to_supabase(date: str, events: list[dict], message: str) -> None:
    """Save digest to Supabase for historical tracking.
    
    Args:
        date: Date string YYYY-MM-DD
        events: List of actionable events
        message: Formatted message
    """
    try:
        supabase = get_supabase_client()
    except ValueError:
        return  # Supabase not configured
    
    # Prepare event summaries (lighter weight than full events)
    event_summaries = [
        {
            "event_id": e.get("event_id"),
            "title": e.get("title"),
            "score": e.get("score"),
            "source": e.get("source"),
            "url": e.get("url"),
        }
        for e in events
    ]
    
    supabase.table("digests").upsert(
        {
            "date": date,
            "events": event_summaries,
            "message": message,
            "event_count": len(events),
        },
        on_conflict="date",
    ).execute()


def main():
    """CLI entry point."""
    message = generate_daily_push()
    print(message)


if __name__ == "__main__":
    main()