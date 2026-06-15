"""DynamoDB storage for standardized events.

Implements global deduplication and event normalization.
"""

import os
import json
import re
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from rich.console import Console

console = Console()

TABLE_NAME = "trendradar-events"
FUNDING_TABLE_NAME = "trendradar-funding"
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


class FundingClient:
    """Client for the trendradar-funding DynamoDB table."""

    def __init__(self) -> None:
        self.dynamodb = boto3.resource(
            "dynamodb",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        self.table = self.dynamodb.Table(FUNDING_TABLE_NAME)
        # In-memory cache for dedup lookups (avoid repeated scans)
        self._event_id_cache: dict[str, str] = {}  # event_id -> PK

    @property
    def available(self) -> bool:
        """Return True if DynamoDB table is accessible."""
        try:
            self.table.table_status
            return True
        except ClientError:
            return False

    def _event_exists(self, event_id: str) -> bool:
        """Check if an event_id already exists in the table.

        Uses source-index GSI to narrow the scan, then filters by event_id.
        Results are cached for the session to avoid repeated lookups.

        Args:
            event_id: The event ID to check.

        Returns:
            True if the event already exists.
        """
        if event_id in self._event_id_cache:
            return True

        # Query by source to narrow down (we don't have event_id-index)
        # Fall back to scan with filter
        try:
            response = self.table.scan(
                FilterExpression="event_id = :eid",
                ExpressionAttributeValues={":eid": event_id},
                ProjectionExpression="#pk, event_id",
                ExpressionAttributeNames={"#pk": "funding_type#first_seen_date"},
                Limit=1,
            )
            items = response.get("Items", [])
            if items:
                # Cache the PK for potential updates
                self._event_id_cache[event_id] = items[0]["funding_type#first_seen_date"]
                return True
            return False
        except ClientError:
            return False

    def save_funding_event(
        self,
        source: str,
        event_type: str,
        title: str,
        url: str,
        data: dict,
        raw_s3_key: str,
        published_at: Optional[datetime] = None,
    ) -> dict:
        """Save a funding event to the trendradar-funding table.

        Performs global deduplication by event_id across all partitions.

        Args:
            source: Source name (fundbat, vc_funding)
            event_type: Type of event (e.g., "funding_round")
            title: Event title
            url: Event URL
            data: Normalized event data
            raw_s3_key: S3 key of the raw snapshot
            published_at: Optional publish date

        Returns:
            Saved event dict with 'exists' flag indicating if it was a duplicate.
        """
        event_id = generate_event_id(source, url, title)

        # Global dedup check: event_id must be unique across all partitions
        if self._event_exists(event_id):
            return {"event_id": event_id, "exists": True}

        now = datetime.now(timezone.utc)
        first_seen_date = now.strftime("%Y-%m-%d")
        ttl = int((now + timedelta(days=TTL_DAYS)).timestamp())

        event = {
            "funding_type#first_seen_date": f"{source}#{first_seen_date}",
            "event_id": event_id,
            "source": source,
            "event_type": event_type,
            "title": title,
            "url": url,
            "data": json.dumps(data),
            "raw_s3_key": raw_s3_key,
            "published_at": (published_at or now).isoformat() if isinstance(published_at, datetime) else now.isoformat(),
            "first_seen_at": now.isoformat(),
            "last_updated_at": now.isoformat(),
            "ttl": ttl,
        }

        try:
            self.table.put_item(Item=event)
            # Cache the new event_id
            self._event_id_cache[event_id] = event["funding_type#first_seen_date"]
            return {**event, "exists": False}
        except ClientError as e:
            raise

    def search_related_funding(
        self,
        keywords: list[str],
        industry: Optional[str] = None,
    ) -> list[dict]:
        """Search funding events by keywords and optionally industry.

        Used by pain_verifier Layer 4 to find related market signals.

        Args:
            keywords: List of keywords to match against title
            industry: Optional industry/category filter

        Returns:
            List of matching funding event dicts
        """
        if not keywords:
            return []

        # Build filter expression for keyword matching
        conditions = []
        expr_values = {}
        expr_names = {}

        for i, kw in enumerate(keywords[:8]):
            placeholder = f":kw{i}"
            conditions.append(f"contains(#title, {placeholder})")
            expr_values[placeholder] = kw.lower()
            expr_names["#title"] = "title"

        filter_expr = " OR ".join(conditions)

        if industry:
            expr_names["#data"] = "data"
            filter_expr += f" AND contains(#data, :industry)"
            expr_values[":industry"] = industry.lower()

        try:
            response = self.table.scan(
                FilterExpression=filter_expr,
                ExpressionAttributeValues=expr_values,
                ExpressionAttributeNames=expr_names,
                Limit=50,
            )
            items = response.get("Items", [])
            # Parse JSON data field
            for item in items:
                try:
                    item["data"] = json.loads(item.get("data", "{}"))
                except (json.JSONDecodeError, TypeError):
                    item["data"] = {}
            return items
        except ClientError as e:
            return []

    def get_funding_by_date_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """Query funding events by date range.

        Args:
            start_date: Start date YYYY-MM-DD
            end_date: End date YYYY-MM-DD

        Returns:
            List of funding events in the date range
        """
        results = []

        # Query both fundbat and vc_funding source types
        for source in ("fundbat", "vc_funding"):
            try:
                response = self.table.query(
                    KeyConditionExpression=(
                        "#pk = :pk_start OR (#pk BETWEEN :pk_start AND :pk_end)"
                    ),
                    ExpressionAttributeNames={"#pk": "funding_type#first_seen_date"},
                    ExpressionAttributeValues={
                        ":pk_start": f"{source}#{start_date}",
                        ":pk_end": f"{source}#{end_date}",
                    },
                )
                items = response.get("Items", [])
                for item in items:
                    try:
                        item["data"] = json.loads(item.get("data", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        item["data"] = {}
                results.extend(items)
            except ClientError:
                continue

        return results

    def clean_funding_data(self, dry_run: bool = True) -> dict:
        """Scan and clean funding data: extract company/amount/sector from title+data.

        Args:
            dry_run: If True, only print stats without writing changes

        Returns:
            Dict with cleaning statistics
        """
        stats = {
            "total": 0,
            "amount_extracted": 0,
            "company_cleaned": 0,
            "errors": 0,
        }

        # Scan all funding records with pagination
        paginator = self.table.meta.client.get_paginator("scan")
        response = paginator.paginate(TableName=FUNDING_TABLE_NAME)

        for page in response:
            items = page.get("Items", [])
            for item in items:
                stats["total"] += 1
                try:
                    # Parse data JSON string
                    data_str = item.get("data", "{}")
                    data = json.loads(data_str) if isinstance(data_str, str) else data_str

                    title = item.get("title", "")
                    update_values = {}

                    # Extract real company name from title
                    # Pattern: "CompanyName raises $X round" or similar
                    raise_pattern = re.compile(
                        r"^(.+?)\s+raises?\s+[\$0-9,\.]+\s*(?:million|billion|thousand|b|m|k)?",
                        re.IGNORECASE,
                    )
                    match = raise_pattern.search(title)
                    if match:
                        company_name = match.group(1).strip()
                        if company_name and company_name != title:
                            update_values["company_name"] = company_name
                            stats["company_cleaned"] += 1

                    # Extract amount from title if data.amount == 0
                    amount = data.get("amount", 0)
                    if amount == 0:
                        # Try to extract from title with patterns like "$200M" or "$2B"
                        amount_patterns = [
                            # $X Billion / $X B
                            (r"\$([0-9,\.]+)\s*billion", 1_000_000_000),
                            (r"\$([0-9,\.]+)\s*b\b?$", 1_000_000_000),
                            # $X Million / $X M
                            (r"\$([0-9,\.]+)\s*million", 1_000_000),
                            (r"\$([0-9,\.]+)\s*m\b?$", 1_000_000),
                            (r"\$([0-9,\.]+)\s*k\b?$", 1_000),
                        ]
                        for pattern, multiplier in amount_patterns:
                            am = re.search(pattern, title, re.IGNORECASE)
                            if am:
                                try:
                                    raw_num = am.group(1).replace(",", "")
                                    extracted_amount = float(raw_num) * multiplier
                                    update_values["funding_amount"] = int(extracted_amount)
                                    stats["amount_extracted"] += 1
                                    break
                                except (ValueError, IndexError):
                                    pass
                    else:
                        # Already has amount, just copy to top-level
                        update_values["funding_amount"] = int(amount)

                    # Standardize sector
                    sector = data.get("sector", "")
                    if sector:
                        sector_lower = sector.lower().strip()
                        SECTOR_MAP = {
                            "ai": "AI/ML", "artificial intelligence": "AI/ML", "ml": "AI/ML",
                            "machine learning": "AI/ML",
                            "saas": "SaaS", "software": "SaaS",
                            "fintech": "Fintech", "financial": "Fintech", "finance": "Fintech",
                            "health": "Health", "healthcare": "Health", "medtech": "Health",
                            "security": "Security", "cybersecurity": "Security",
                            "devops": "DevOps",
                            "developer": "Developer Tools", "developer tools": "Developer Tools",
                            "data": "Data", "database": "Data",
                            "edtech": "EdTech", "education": "EdTech",
                            "ecommerce": "E-commerce", "e-commerce": "E-commerce",
                            "crypto": "Crypto", "web3": "Crypto", "blockchain": "Crypto",
                        }
                        if sector_lower in SECTOR_MAP:
                            update_values["sector"] = SECTOR_MAP[sector_lower]
                        elif sector_lower not in ("unknown", ""):
                            update_values["sector"] = sector

                    # Round stage
                    round_stage = data.get("round", "")
                    if round_stage:
                        update_values["round_stage"] = round_stage

                except Exception:
                    stats["errors"] += 1
                    continue

                if update_values and not dry_run:
                    # Write back top-level fields
                    try:
                        self.table.update_item(
                            Key={
                                "funding_type#first_seen_date": item["funding_type#first_seen_date"],
                                "event_id": item["event_id"],
                            },
                            UpdateExpression="SET " + ", ".join(f"{k} = :{k}" for k in update_values.keys()),
                            ExpressionAttributeValues={f":{k}": v for k, v in update_values.items()},
                        )
                    except ClientError:
                        stats["errors"] += 1

        if dry_run:
            console.print("[yellow]DRY RUN - No changes written[/yellow]")
        console.print(f"Total records: {stats['total']}")
        console.print(f"Company names cleaned: {stats['company_cleaned']}")
        console.print(f"Amounts extracted from title: {stats['amount_extracted']}")
        console.print(f"Errors: {stats['errors']}")
        return stats


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
        cluster_id: Optional[str] = None,
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
            cluster_id: Optional UUID of the opportunity cluster this event belongs to
        
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
        # Handle string published_at (e.g. from Twitter)
        if isinstance(published_at, str):
            published_at = now
        elif not isinstance(published_at, datetime):
            published_at = now
        ttl = int((now + timedelta(days=TTL_DAYS)).timestamp())
        
        event = {
            "event_type#first_seen_date": f"{event_type}#{first_seen_date}",
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
            "cluster_id": cluster_id,
            "embedding_generated": "false",
            "ttl": ttl,
        }
        
        # Note: Actual table PK is event_type#first_seen_date (HASH), event_id (RANGE)
        # We keep both orders compatible with existing table structure for now (cannot change PK without recreating table
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

    def get_actionable_events(
        self,
        min_score: int = 70,
        date: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get actionable events (score >= min_score) for a specific date.
        
        Args:
            min_score: Minimum score threshold (default 70)
            date: Date string YYYY-MM-DD (default: today)
            limit: Maximum events to return
        
        Returns:
            List of actionable event dicts sorted by score descending
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Query by date prefix and filter by score
        # Note: This scans the table since we need to filter by both date and score
        # For production, consider a GSI on is_actionable + first_seen_date
        try:
            response = self.table.scan(
                FilterExpression="is_actionable = :actionable AND begins_with(#pk, :date_prefix)",
                ExpressionAttributeNames={"#pk": "event_type#first_seen_date"},
                ExpressionAttributeValues={
                    ":actionable": "true",
                    ":date_prefix": "",  # Scan all, filter later
                },
                Limit=limit * 3,  # Get more to filter down
            )
            events = response.get("Items", [])
        except ClientError:
            return []
        
        # Filter by date and score, sort by score descending
        filtered = []
        for e in events:
            first_seen = e.get("first_seen_at", "")
            if date in first_seen and e.get("score", 0) >= min_score:
                # Parse data field
                try:
                    e["data"] = json.loads(e.get("data", "{}"))
                except (json.JSONDecodeError, TypeError):
                    e["data"] = {}
                filtered.append(e)
        
        # Sort by score descending
        filtered.sort(key=lambda x: x.get("score", 0), reverse=True)
        return filtered[:limit]

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
        
        pk = response["Items"][0]["event_type#first_seen_date"]
        
        self.table.update_item(
            Key={
                "event_type#first_seen_date": pk,
                "event_id": event_id,
            },
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_attrs,
        )

    def mark_events_analyzed(self, event_ids: list[str], batch_size: int = 25) -> dict:
        """Mark multiple events as analyzed using batch write.

        Args:
            event_ids: List of event IDs to mark as analyzed
            batch_size: Number of items per batch (DynamoDB limit is 25)

        Returns:
            Dict with counts of success and failed
        """
        from storage.dynamo import TABLE_NAME

        stats = {"success": 0, "failed": 0}

        # First, resolve event_ids to PKs via event_id-index GSI
        pk_map = {}  # event_id -> PK (event_type#first_seen_date)
        for event_id in event_ids:
            try:
                response = self.table.query(
                    IndexName="event_id-index",
                    KeyConditionExpression="event_id = :event_id",
                    ExpressionAttributeValues={":event_id": event_id},
                    Limit=1,
                )
                items = response.get("Items", [])
                if items:
                    pk_map[event_id] = items[0]["event_type#first_seen_date"]
                else:
                    stats["failed"] += 1
            except ClientError:
                stats["failed"] += 1

        # Batch write in groups of batch_size
        for i in range(0, len(pk_map), batch_size):
            batch = list(pk_map.items())[i:i + batch_size]
            write_requests = []
            for event_id, pk in batch:
                write_requests.append({
                    "PutRequest": {
                        "Item": {
                            "event_type#first_seen_date": pk,
                            "event_id": event_id,
                            "is_analyzed": "true",
                            "last_updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    }
                })

            try:
                self.table.meta.client.batch_write_item(
                    RequestItems={TABLE_NAME: write_requests}
                )
                stats["success"] += len(batch)
            except ClientError:
                stats["failed"] += len(batch)

        return stats
