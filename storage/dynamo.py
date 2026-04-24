"""DynamoDB storage for standardized events.

Implements global deduplication and event normalization.
"""

import os
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, list, dict

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = "trendradar-events"
TTL_DAYS = 90  # Events auto-expire after 90 days


def generate_event_id(source: str, url: str, title: str) -> str:
    """Generate global unique event ID for deduplication.
    
    Args:
        source: Source name
        url: Event URL
        title: Event title
    
    Returns:
        MD5 hash of the concatenated fields
    """
    key = f"{source}:{url}:{title}".lower().strip()
    return hashlib.md5(key.encode("utf-8")).hexdigest()


class DynamoClient:
    """Client for interacting with DynamoDB events table."""

    def __init__(self) -> None:
        self.dynamodb = boto3.resource(
            "dynamodb",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        self.table = self.dynamodb.Table(TABLE_NAME)

    @property
    def available(self) -> bool:
        """Return True if DynamoDB table is accessible."""
        try:
            self.table.table_status
            return True
        except ClientError:
            return False

    def event_exists(self, event_id: str) -> bool:
        """Check if an event already exists in the table.
        
        Args:
            event_id: Global unique event ID
        
        Returns:
            True if event exists
        """
        try:
            response = self.table.query(
                IndexName="event_id-index",
                KeyConditionExpression="event_id = :event_id",
                ExpressionAttributeValues={":event_id": event_id},
                Limit=1,
            )
            return len(response.get("Items", [])) > 0
        except ClientError:
            return False

    def save_event(
        self,
        source: str,
        event_type: str,
        title: str,
        url: str,
        data: dict,
        raw_s3_key: str,
        published_at: Optional[datetime] = None,
        raw_signal_ids: Optional[list[str]] = None,
        score: Optional[int] = None,
    ) -> dict:
        """Save a standardized event to DynamoDB.
        
        Args:
            source: Source name
            event_type: Type of event (e.g., "yc_batch", "funding", "product")
            title: Event title
            url: Event URL
            data: Normalized event data
            raw_s3_key: S3 key of the raw snapshot
            published_at: Optional publish date of the event
            raw_signal_ids: Optional list of raw signal IDs from multiple sources
            score: Optional LLM generated score (0-100)
        
        Returns:
            Saved event dict
        """
        event_id = generate_event_id(source, url, title)
        
        # Skip duplicates
        if self.event_exists(event_id):
            return {"event_id": event_id, "exists": True}
        
        now = datetime.now(timezone.utc)
        first_seen_date = now.strftime("%Y-%m-%d")
        published_at = published_at or now
        ttl = int((now + timedelta(days=TTL_DAYS)).timestamp())
        
        event = {
            "first_seen_date#event_type": f"{first_seen_date}#{event_type}",
            "event_id": event_id,
            "source": source,
            "event_type": event_type,
            "title": title,
            "url": url,
            "data": json.dumps(data),  # Store normalized data as JSON string
            "raw_s3_key": raw_s3_key,
            "published_at": published_at.isoformat(),
            "first_seen_at": now.isoformat(),
            "last_updated_at": now.isoformat(),
            "raw_signal_ids": raw_signal_ids or [],
            "is_analyzed": "false",
            "score": score,
            "ttl": ttl,
        }
        
        self.table.put_item(Item=event)
        return {**event, "exists": False}

    def get_unanalyzed_events(self, limit: int = 100) -> list[dict]:
        """Get all events that haven't been analyzed yet.
        
        Args:
            limit: Maximum number of events to return
        
        Returns:
            List of unanalyzed event dicts
        """
        response = self.table.query(
            IndexName="is_analyzed-index",
            KeyConditionExpression="is_analyzed = :val",
            ExpressionAttributeValues={":val": "false"},
            Limit=limit,
        )
        events = response.get("Items", [])
        # Parse JSON data field
        for e in events:
            try:
                e["data"] = json.loads(e["data"])
            except (json.JSONDecodeError, KeyError):
                pass
        return events

    def mark_analyzed(self, event_id: str, score: Optional[int] = None) -> None:
        """Mark an event as analyzed, optionally update its score.
        
        Args:
            event_id: Global event ID
            score: Optional LLM generated score
        """
        update_expr = "SET is_analyzed = :analyzed, last_updated_at = :now"
        expr_attrs = {
            ":analyzed": "true",
            ":now": datetime.now(timezone.utc).isoformat(),
        }
        
        if score is not None:
            update_expr += ", score = :score"
            expr_attrs[":score"] = score
        
        # Find the event to get the PK
        response = self.table.query(
            IndexName="event_id-index",
            KeyConditionExpression="event_id = :event_id",
            ExpressionAttributeValues={":event_id": event_id},
            Limit=1,
        )
        if not response.get("Items"):
            return
        
        pk = response["Items"][0]["first_seen_date#event_type"]
        
        self.table.update_item(
            Key={
                "first_seen_date#event_type": pk,
                "event_id": event_id,
            },
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_attrs,
        )
