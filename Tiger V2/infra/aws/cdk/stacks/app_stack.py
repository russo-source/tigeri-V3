import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class AppStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        db_secret: secretsmanager.ISecret,
        documents_bucket: s3.Bucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cluster = ecs.Cluster(self, "TigeriCluster", vpc=vpc, container_insights=True)

        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "TigeriApi",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=2,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset("../../.."),  # build context = repo root
                container_port=8000,
                environment={
                    "TIGERI_ENV": "aws",
                    "TIGERI_LOG_LEVEL": "INFO",
                },
                secrets={
                    "TIGERI_DATABASE_URL": ecs.Secret.from_secrets_manager(db_secret),
                },
            ),
            public_load_balancer=True,
        )
        documents_bucket.grant_read_write(service.task_definition.task_role)
