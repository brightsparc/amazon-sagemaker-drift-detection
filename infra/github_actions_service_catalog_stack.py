from aws_cdk import (
    core,
    aws_iam as iam,
    aws_servicecatalog as servicecatalog,
    aws_secretsmanager as secretsmanager,
)
import json

from infra.generate_sc_template import generate_template
from infra.github_actions_pipeline_stack import GitHubActionsPipelineStack


# Create a Portfolio and Product
# see: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_servicecatalog.html
class GitHubActionsServiceCatalogStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        execution_role_arn = core.CfnParameter(
            self,
            "ExecutionRoleArn",
            type="String",
            description="The SageMaker Studio execution role",
            min_length=1,
            allowed_pattern="^arn:aws[a-z\\-]*:iam::\\d{12}:role/?[a-zA-Z_0-9+=,.@\\-_/]+$",
        )

        portfolio_name = core.CfnParameter(
            self,
            "PortfolioName",
            type="String",
            description="The name of the portfolio",
            default="SageMaker Organization Templates",
            min_length=1,
        )

        portfolio_owner = core.CfnParameter(
            self,
            "PortfolioOwner",
            type="String",
            description="The owner of the portfolio",
            default="administrator",
            min_length=1,
            max_length=50,
        )

        product_version = core.CfnParameter(
            self,
            "ProductVersion",
            type="String",
            description="The product version to deploy",
            default="1.0",
            min_length=1,
        )

        iam_user_name = core.CfnParameter(
            self,
            "IAM user name",
            type="String",
            description="IAM user name to create for github actions",
            default="sagemaker-github-actions-user",
            min_length=1,
        ).value_as_string

        # Create the launch role
        products_launch_role_name = self.node.try_get_context(
            "drift:ProductsLaunchRoleName"
        )
        products_launch_role = iam.Role.from_role_arn(
            self,
            "GitHubLaunchRole",
            role_arn=f"arn:{self.partition}:iam::{self.account}:role/{products_launch_role_name}",
        )

        # Create sagemaker secret in github actions pipeline
        products_launch_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:CreateSecret",
                    "secretsmanager:TagResource",
                ],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:sagemaker-*"
                ],
            )
        )

        # Create an IAM User with access key
        github_user = iam.User(self, "GitHubUser", user_name=iam_user_name)
        github_access_key = iam.CfnAccessKey(
            self, "GitHubAccessKey", user_name=github_user.user_name
        )

        # Add s3 permissions to upload to sagemaker buckets
        github_user.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:CreateBucket",
                    "s3:GetBucket*",
                    "s3:ListAllMyBuckets",
                    "s3:ListBucket",
                    "s3:GetObject*",
                    "s3:PutObject*",
                ],
                resources=["arn:aws:s3:::sagemaker-*"],
            )
        )

        # Add read-only sagemaker permissions, and start pipeline
        github_user.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "sagemaker:Describe*",
                    "sagemaker:List*",
                    "sagemaker:Search",
                    "sagemaker:StartPipelineExecution",
                ],
                resources=["*"],
            )
        )

        # Allow create sagemaker lambda functionss
        lambda_policy = iam.PolicyStatement(
            actions=[
                "lambda:*",
            ],
            resources=[
                f"arn:aws:lambda:{self.region}:{self.account}:function:sagemaker-*"
            ],
        )
        github_user.add_to_principal_policy(lambda_policy)

        # Create Github secret referencing the access key and secret
        github_secret = secretsmanager.Secret(
            self,
            "GitHubAccessToken",
            secret_name=iam_user_name,
        )
        cfn_github_secret: secretsmanager.CfnSecret = github_secret.node.default_child
        cfn_github_secret.generate_secret_string = None
        cfn_github_secret.secret_string = json.dumps(
            {
                "AccessKeyId": github_access_key.ref,
                "SecretAccessKey": github_access_key.attr_secret_access_key,
            }
        )

        # Output the secret key name
        core.CfnOutput(self, "SecretKey", value=github_secret.secret_name)

        # Get the service catalog role for all permssions (if None CDK will create new roles)
        # CodeBuild and CodePipeline resources need to start with "sagemaker-" to be within default policy
        products_use_role_name = self.node.try_get_context("drift:ProductsUseRoleName")
        if products_use_role_name:
            products_use_role = iam.Role.from_role_arn(
                self,
                "GitHubProductsUseRole",
                f"arn:{self.partition}:iam::{self.account}:role/{products_use_role_name}",
            )

            # Allow assuming role on self, as the CDK CodePipeline requires this
            # see: https://github.com/aws/aws-cdk/issues/5941
            products_use_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["sts:AssumeRole"],
                    resources=[products_use_role.role_arn],
                )
            )

            # Add permissions to allow adding auto scaling for production deployment
            products_use_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=[
                        "application-autoscaling:DeregisterScalableTarget",
                        "application-autoscaling:DeleteScalingPolicy",
                        "application-autoscaling:DescribeScalingPolicies",
                        "application-autoscaling:PutScalingPolicy",
                        "application-autoscaling:DescribeScalingPolicies",
                        "application-autoscaling:RegisterScalableTarget",
                        "application-autoscaling:DescribeScalableTargets",
                        "cloudwatch:DeleteAlarms",
                        "cloudwatch:DescribeAlarms",
                        "cloudwatch:PutMetricAlarm",
                        "codepipeline:PutJobSuccessResult",
                        "codepipeline:PutJobFailureResult",
                    ],
                    resources=["*"],
                )
            )

            products_use_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["iam:CreateServiceLinkedRole"],
                    resources=[
                        f"arn:aws:iam::{self.account}:role/aws-service-role/sagemaker.application-autoscaling.amazonaws.com/AWSServiceRoleForApplicationAutoScaling_SageMakerEndpoint"
                    ],
                    conditions={
                        "StringLike": {
                            "iam:AWSServiceName": "sagemaker.application-autoscaling.amazonaws.com"
                        }
                    },
                )
            )

            # Add permissions to get/create lambda in batch pipeline
            products_use_role.add_to_principal_policy(lambda_policy)

            # Allow github user to pass role to product use role
            github_user.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=[
                        "iam:PassRole",
                    ],
                    resources=[products_use_role.role_arn],
                )
            )

        portfolio = servicecatalog.Portfolio(
            self,
            "Portfolio",
            display_name=portfolio_name.value_as_string,
            provider_name=portfolio_owner.value_as_string,
            description="Organization templates for github actions pipeline",
        )

        product = servicecatalog.CloudFormationProduct(
            self,
            "Product",
            owner=portfolio_owner.value_as_string,
            product_name="Amazon SageMaker drift detection template for github actions",
            product_versions=[
                servicecatalog.CloudFormationProductVersion(
                    cloud_formation_template=servicecatalog.CloudFormationTemplate.from_asset(
                        generate_template(
                            stack=GitHubActionsPipelineStack,
                            stack_name="github-actions-pipeline",
                            strip_policies=True,
                        )
                    ),
                    product_version_name=product_version.value_as_string,
                )
            ],
            description="This template requires a GitHub User and token which are stored in Amazon Secrets Manager for callback into GitHub Actions workflows for when a model is approved in the registry, or drift is deteted",
        )

        # Create portfolio associate that depends on products
        portfolio_association = servicecatalog.CfnPortfolioPrincipalAssociation(
            self,
            "PortfolioPrincipalAssociation",
            portfolio_id=portfolio.portfolio_id,
            principal_arn=execution_role_arn.value_as_string,
            principal_type="IAM",
        )
        portfolio_association.node.add_dependency(product)

        # Add product tags, and create role constraint for each product
        portfolio.add_product(product)
        core.Tags.of(product).add(key="sagemaker:studio-visibility", value="true")
        role_constraint = servicecatalog.CfnLaunchRoleConstraint(
            self,
            "LaunchRoleConstraint",
            portfolio_id=portfolio.portfolio_id,
            product_id=product.product_id,
            role_arn=products_launch_role.role_arn,
            description=f"Launch as {products_launch_role.role_arn}",
        )
        role_constraint.add_depends_on(portfolio_association)
