"""AWS CDK stack for TrendRadar v2 core infrastructure."""

from aws_cdk import Stack, aws_dynamodb as dynamodb, aws_s3 as s3
from constructs import Construct


class TrendRadarStack(Stack):
    """Provision S3 and DynamoDB resources for the TrendRadar pipeline."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.raw_bucket = s3.Bucket(
            self,
            "TrendRadarRawBucket",
            bucket_name="trendradar-raw",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,  # Enable versioning for data safety
        )

        self.events_table = dynamodb.Table(
            self,
            "TrendRadarEventsTable",
            table_name="trendradar-events",
            partition_key=dynamodb.Attribute(
                name="event_type#first_seen_date",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="event_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            time_to_live_attribute="ttl",
        )

        self.events_table.add_global_secondary_index(
            index_name="event_id-index",
            partition_key=dynamodb.Attribute(
                name="event_id",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Store is_analyzed as "true"/"false" since DynamoDB index keys are scalar types.
        self.events_table.add_global_secondary_index(
            index_name="is_analyzed-index",
            partition_key=dynamodb.Attribute(
                name="is_analyzed",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

# Remove redundant event_sources table, use raw_signal_ids array in events table instead
        pass
