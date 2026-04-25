"""Manually update infrastructure properties without CDK redeploy."""

import boto3
from botocore.exceptions import ClientError

def enable_s3_versioning():
    """Enable versioning on S3 raw bucket."""
    s3 = boto3.client('s3')
    try:
        s3.put_bucket_versioning(
            Bucket='trendradar-raw',
            VersioningConfiguration={'Status': 'Enabled'}
        )
        print("✅ S3 versioning enabled for trendradar-raw")
        return True
    except ClientError as e:
        print(f"❌ Failed to enable S3 versioning: {e}")
        return False

def enable_dynamodb_ttl():
    """Enable TTL on DynamoDB events table."""
    dynamodb = boto3.client('dynamodb')
    try:
        dynamodb.update_time_to_live(
            TableName='trendradar-events',
            TimeToLiveSpecification={
                'Enabled': True,
                'AttributeName': 'ttl'
            }
        )
        print("✅ DynamoDB TTL enabled for trendradar-events (attribute: ttl)")
        return True
    except ClientError as e:
        print(f"❌ Failed to enable DynamoDB TTL: {e}")
        return False

def describe_dynamodb_table():
    """Describe current DynamoDB table structure."""
    dynamodb = boto3.client('dynamodb')
    try:
        response = dynamodb.describe_table(TableName='trendradar-events')
        table = response['Table']
        print(f"\n📊 DynamoDB Table Status:")
        print(f"   TableName: {table['TableName']}")
        print(f"   TableStatus: {table['TableStatus']}")
        print(f"   KeySchema: {[k['AttributeName'] + ' (' + k['KeyType'] + ')' for k in table['KeySchema']]}")
        print(f"   TTL: {table.get('TimeToLiveDescription', {}).get('TimeToLiveStatus', 'NOT_ENABLED')}")
        return True
    except ClientError as e:
        print(f"❌ Failed to describe DynamoDB table: {e}")
        return False

if __name__ == "__main__":
    print("Updating TrendRadar infrastructure...\n")
    enable_s3_versioning()
    enable_dynamodb_ttl()
    describe_dynamodb_table()
    print("\n✅ Infrastructure updates completed!")
    print("\n⚠️  Note: DynamoDB PK cannot be changed without recreating the table.")
    print("   Current PK is: event_type#first_seen_date (HASH) + event_id (RANGE)")
    print("   This is acceptable for now; we can handle the order in code.")
