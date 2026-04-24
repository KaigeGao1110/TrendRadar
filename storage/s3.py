"""S3 storage backend for raw snapshot data.

Stores all raw crawled data in S3 with path format: s3://trendradar-raw/{source}/{year}/{month}/{day}/{uuid}.json
"""

import os
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

BUCKET_NAME = "trendradar-raw"


class S3Client:
    """Client for interacting with S3 raw storage."""

    def __init__(self) -> None:
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        self.bucket_name = BUCKET_NAME

    @property
    def available(self) -> bool:
        """Return True if S3 bucket is accessible."""
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            return True
        except ClientError:
            return False

    def save_snapshot(self, source: str, data: dict) -> str:
        """Save a raw snapshot to S3.
        
        Args:
            source: Source name (e.g., "hackernews", "producthunt")
            data: Raw snapshot data
        
        Returns:
            S3 object key of the saved snapshot
        """
        now = datetime.now(timezone.utc)
        # Generate path: source/YYYY/MM/DD/uuid.json
        key = f"{source}/{now.year}/{now.month:02d}/{now.day:02d}/{uuid.uuid4()}.json"
        
        # Convert to JSON string
        json_data = json.dumps(data, indent=2, default=str)
        
        # Upload to S3
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=json_data,
            ContentType="application/json",
        )
        
        return key

    def get_snapshot(self, key: str) -> Optional[dict]:
        """Get a raw snapshot from S3 by key.
        
        Args:
            key: S3 object key
        
        Returns:
            Parsed snapshot data, or None if not found
        """
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def list_snapshots(self, source: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> list[str]:
        """List all snapshot keys for a source, optionally filtered by date range.
        
        Args:
            source: Source name
            start_date: Optional start date (UTC)
            end_date: Optional end date (UTC)
        
        Returns:
            List of S3 object keys
        """
        prefix = f"{source}/"
        if start_date:
            prefix += f"{start_date.year}/{start_date.month:02d}/"
        if end_date:
            # For simplicity, just filter by year/month if end_date is provided
            prefix += f"{end_date.year}/{end_date.month:02d}/"
        
        keys = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            if "Contents" not in page:
                continue
            for obj in page["Contents"]:
                keys.append(obj["Key"])
        
        return keys
