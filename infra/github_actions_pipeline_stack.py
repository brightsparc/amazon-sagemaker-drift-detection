from aws_cdk import (
    core,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
)
import json


class GitHubActionsPipelineStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Define required parmeters
        project_name = core.CfnParameter(
            self,
            "SageMakerProjectName",
            type="String",
            description="The name of the SageMaker project.",
            min_length=1,
            max_length=32,
        ).value_as_string
        project_id = core.CfnParameter(
            self,
            "SageMakerProjectId",
            type="String",
            min_length=1,
            max_length=16,
            description="Service generated Id of the project.",
        ).value_as_string
        github_user = core.CfnParameter(
            self,
            "GitHubUser",
            type="String",
            min_length=1,
            max_length=39,
            description="GitHub User",
        ).value_as_string
        github_token = core.CfnParameter(
            self,
            "GitHubToken",
            type="String",
            no_echo=True,
            min_length=1,
            max_length=255,
            description="GitHub Token",
        ).value_as_string

        # Create the s3 artifact (name must be < 63 chars)
        artifact_bucket_name = f"sagemaker-project-{project_id}-{self.region}"
        s3_artifact = s3.Bucket(
            self,
            "S3Artifact",
            bucket_name=artifact_bucket_name,
            removal_policy=core.RemovalPolicy.DESTROY,
        )

        core.CfnOutput(self, "ArtifactBucket", value=s3_artifact.bucket_name)

        # Create a secret with string containing JSON for user and token
        # see: https://github.com/aws/aws-cdk/issues/5810
        github_secret = secretsmanager.Secret(
            self,
            "GitHubAccessToken",
            secret_name=f"sagemaker-{project_id}-{construct_id}",
        )
        cfn_github_secret: secretsmanager.CfnSecret = github_secret.node.default_child
        cfn_github_secret.generate_secret_string = None
        cfn_github_secret.secret_string = json.dumps(
            {
                "user": github_user,
                "token": github_token,
            }
        )

        # Get the service catalog role for all permssions (if None CDK will create new roles)
        # CodeBuild and CodePipeline resources need to start with "sagemaker-" to be within default policy
        products_use_role_name = self.node.try_get_context("drift:ProductsUseRoleName")
        if products_use_role_name:
            service_catalog_role = iam.Role.from_role_arn(
                self,
                "ProductsUseRole",
                f"arn:{self.partition}:iam::{self.account}:role/{products_use_role_name}",
            )
            # Use the service catalog role for all roles
            lambda_role = service_catalog_role
        else:
            # Create unique scope roles per service, so that permissions can be added in build/deploy stacks
            lambda_role = iam.Role(
                self,
                "LambdaRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                path="/service-role/",
            )

            # Add cloudwatch logs
            logs_policy = iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
            lambda_role.add_to_policy(logs_policy)

            # Add permissions to create secrets
            github_secret.grant_read(lambda_role)

        # Load the lambda pipeline change code
        with open("lambda/lambda_github_dispatch.py", encoding="utf8") as fp:
            lambda_github_dispatch_code = fp.read()

        lambda_github_dispatch = lambda_.Function(
            self,
            "GitHubDispatch",
            function_name=f"sagemaker-{project_name}-github-dispatch",
            code=lambda_.Code.from_inline(lambda_github_dispatch_code),
            role=lambda_role,
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_8,
            timeout=core.Duration.seconds(3),
            memory_size=128,
            environment={"LOG_LEVEL": "INFO"},
        )

        # Define the lambda event input passing the secret, repo, workflow and branch
        events.Rule(
            self,
            "ModelRegistryRule",
            rule_name=f"sagemaker-{project_id}-registry-{construct_id}",  # TEMP: Shorten with project_id
            description="Rule to trigger a deployment when SageMaker Model registry is updated with a new model package.",
            event_pattern=events.EventPattern(
                source=["aws.sagemaker"],
                detail_type=["SageMaker Model Package State Change"],
                detail={
                    "ModelPackageGroupName": [
                        project_name,
                    ],
                    "ModelApprovalStatus": [
                        "Approved",
                        "Rejected",
                    ],
                },
            ),
            targets=[
                targets.LambdaFunction(
                    lambda_github_dispatch,
                    event=events.RuleTargetInput.from_object(
                        {
                            "SecretId": github_secret.secret_name,
                            "Repo": project_name,
                            "EventType": "deploy",
                        }
                    ),
                )
            ],
        )

        events.Rule(
            self,
            "DriftRule",
            rule_name=f"sagemaker-{project_id}-drift-{construct_id}",  # TEMP: Shorten with project_id
            description="Rule to start SM pipeline when drift has been detected.",
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={
                    "alarmName": [
                        f"sagemaker-{project_name}-staging-threshold",
                        f"sagemaker-{project_name}-prod-threshold",
                        f"sagemaker-{project_name}-batch-staging-threshold",
                        f"sagemaker-{project_name}-batch-prod-threshold",
                    ],
                    "state": {"value": ["ALARM"]},
                },
            ),
            targets=[
                targets.LambdaFunction(
                    lambda_github_dispatch,
                    event=events.RuleTargetInput.from_object(
                        {
                            "SecretId": github_secret.secret_name,
                            "Repo": project_name,
                            "EventType": "build",
                        }
                    ),
                )
            ],
        )
