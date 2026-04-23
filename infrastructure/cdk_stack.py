"""AWS CDK stack for TrendRadar v2 core infrastructure."""

from aws_cdk import Duration, Stack, aws_dynamodb as dynamodb, aws_s3 as s3
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
            lifecycle_rules=[
                s3.LifecycleRule(
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=Duration.days(90),
                        )
                    ],
                    expiration=Duration.days(365),
                )
            ],
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

        self.event_sources_table = dynamodb.Table(
            self,
            "TrendRadarEventSourcesTable",
            table_name="trendradar-event-sources",
            partition_key=dynamodb.Attribute(
                name="raw_signal_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="event_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
        )
