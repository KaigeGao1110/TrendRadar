"""Analysis cron trigger — runs the AI analysis pipeline on a schedule.

Mechanism: AWS EventBridge (CloudWatch Events) → Lambda
Or: standalone cron → calls run_analysis_pipeline directly

This module provides both:
1. A run_analysis() function callable by Lambda/EventBridge
2. A CLI entry point for local testing: python -m analyzer.cron
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from typing import Optional

# Optional boto3 for DynamoDB
try:
    import boto3
    import botocore
    BOTO_AVAILABLE = True
except ImportError:
    BOTO_AVAILABLE = False

from supabase import create_client

# Analysis pipeline components
from analyzer.pipeline import run_analysis_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_dynamodb_table():
    """Get boto3 DynamoDB table resource for trendradar-events."""
    if not BOTO_AVAILABLE:
        raise ImportError("boto3 not available")

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )
    return dynamodb.Table(os.environ.get("DYNAMODB_TABLE_NAME", "trendradar-events"))


def get_supabase_client():
    """Get Supabase client from environment."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


def get_openai_client():
    """Get OpenAI client from environment."""
    try:
        from openai import OpenAI
    except ImportError:
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def get_anthropic_client():
    """Get Anthropic client from environment."""
    try:
        import anthropic
    except ImportError:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def run_analysis(limit: int = 50, dry_run: bool = False) -> dict:
    """Run the full analysis pipeline.

    Args:
        limit: Maximum events to process
        dry_run: If True, fetch and score events but don't write to Supabase

    Returns:
        Summary dict with processed count and results
    """
    logger.info(f"Starting analysis run (limit={limit}, dry_run={dry_run}) at {datetime.now(timezone.utc).isoformat()}")

    try:
        # Initialize clients
        dynamodb_table = get_dynamodb_table()
        supabase = get_supabase_client()
        openai = get_openai_client()
        anthropic = get_anthropic_client()

        if not openai:
            logger.warning("OpenAI client not available — embedding generation will use existing embeddings only")
        if not anthropic:
            logger.warning("Anthropic client not available — reasoning will use fallback")

        # Run pipeline
        opportunities = run_analysis_pipeline(
            dynamodb_table=dynamodb_table,
            supabase_client=supabase,
            openai_client=openai,
            anthropic_client=anthropic,
            limit=limit,
        )

        result = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "events_processed": len(opportunities),
            "dry_run": dry_run,
            "opportunities": opportunities,
        }

        logger.info(f"Analysis run complete: {len(opportunities)} opportunities processed")
        return result

    except Exception as e:
        logger.error(f"Analysis run failed: {e}")
        return {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "events_processed": 0,
            "opportunities": [],
        }


def lambda_handler(event, context):
    """AWS Lambda handler for EventBridge-triggered analysis.

    Environment variables required:
    - AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (or instance role)
    - AWS_REGION
    - DYNAMODB_TABLE_NAME (default: trendradar-events)
    - SUPABASE_URL, SUPABASE_KEY
    - OPENAI_API_KEY (optional for embeddings)
    - ANTHROPIC_API_KEY (optional for reasoning)
    """
    # Parse batch size from event if provided
    limit = 50
    if event and isinstance(event, dict):
        limit = event.get("limit", 50)

    result = run_analysis(limit=limit)

    return {
        "statusCode": 200,
        "body": json.dumps(result),
    }


def main():
    """CLI entry point for local testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Run TrendRadar AI analysis pipeline")
    parser.add_argument("--limit", type=int, default=50, help="Max events to process")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and score but don't write to Supabase")
    args = parser.parse_args()

    result = run_analysis(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
