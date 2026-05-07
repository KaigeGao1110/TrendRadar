#!/usr/bin/env python3
"""Clean up duplicate funding events in DynamoDB.

For each unique event_id, keeps the earliest first_seen_at record
and deletes all duplicates.
"""

import os
import sys
import json
from collections import defaultdict
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv
from botocore.exceptions import ClientError

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

TABLE_NAME = "trendradar-funding"


def scan_all_items(table):
    """Scan all items from the table."""
    items = []
    response = table.scan(
        ProjectionExpression='#pk, event_id, first_seen_at',
        ExpressionAttributeNames={'#pk': 'funding_type#first_seen_date'}
    )
    items.extend(response.get('Items', []))
    
    while 'LastEvaluatedKey' in response:
        response = table.scan(
            ExclusiveStartKey=response['LastEvaluatedKey'],
            ProjectionExpression='#pk, event_id, first_seen_at',
            ExpressionAttributeNames={'#pk': 'funding_type#first_seen_date'}
        )
        items.extend(response.get('Items', []))
    
    return items


def main():
    dynamodb = boto3.resource(
        'dynamodb',
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
        region_name=os.environ.get('AWS_REGION', 'us-east-1')
    )
    table = dynamodb.Table(TABLE_NAME)
    
    print(f"Scanning all items from {TABLE_NAME}...")
    items = scan_all_items(table)
    print(f"Total items: {len(items)}")
    
    # Group by event_id
    by_event_id = defaultdict(list)
    for item in items:
        event_id = item.get('event_id')
        if event_id:
            by_event_id[event_id].append(item)
    
    unique_ids = len(by_event_id)
    print(f"Unique event_ids: {unique_ids}")
    
    # Find duplicates
    duplicates = {eid: items for eid, items in by_event_id.items() if len(items) > 1}
    print(f"Duplicate event_ids: {len(duplicates)}")
    
    if not duplicates:
        print("No duplicates found. Nothing to clean up.")
        return
    
    # For each duplicate, keep the earliest first_seen_at, delete the rest
    deleted = 0
    batch_size = 25  # DynamoDB batch limit
    
    for event_id, dup_items in duplicates.items():
        # Sort by first_seen_at to keep the earliest
        dup_items.sort(key=lambda x: x.get('first_seen_at', '9999'))
        keep = dup_items[0]  # Keep the earliest
        to_delete = dup_items[1:]  # Delete the rest
        
        print(f"\nEvent {event_id}:")
        print(f"  Keeping: PK={keep['funding_type#first_seen_date']}, first_seen={keep.get('first_seen_at')}")
        print(f"  Deleting {len(to_delete)} duplicates:")
        
        for item in to_delete:
            try:
                table.delete_item(
                    Key={
                        'funding_type#first_seen_date': item['funding_type#first_seen_date'],
                        'event_id': event_id
                    }
                )
                deleted += 1
                print(f"    - PK={item['funding_type#first_seen_date']}, first_seen={item.get('first_seen_at')}")
            except ClientError as e:
                print(f"    - FAILED to delete: {e}")
    
    print(f"\nDone. Deleted {deleted} duplicate items.")
    print(f"Remaining items: {len(items) - deleted}")


if __name__ == '__main__':
    main()
