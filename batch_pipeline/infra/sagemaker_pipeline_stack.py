from aws_cdk import (
    core,
    aws_cloudwatch as cloudwatch,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_sagemaker as sagemaker,
)

import logging
from batch_config import DriftConfig

logger = logging.getLogger(__name__)

# Create a SageMaker Pipeline resource with a given pipeline_definition
# see: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_sagemaker/CfnPipeline.html


class SageMakerPipelineStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        pipeline_name: str,
        pipeline_description: str,
        pipeline_definition_bucket: str,
        pipeline_definition_key: str,
        sagemaker_role_arn: str,
        lambda_role_arn: str,
        evaluate_drift_function_name: str,
        tags: list,
        drift_config: DriftConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        lambda_role = iam.Role.from_role_arn(self, "LambdaRole", role_arn=lambda_role_arn)

        with open("lambda/lambda_evaluate_drift.py", encoding="utf8") as fp:
            lambda_evaluate_drift_code = fp.read()

        # Return return the lambda function, so we can get the function arn
        self.evaluate_drift_lambda = lambda_.Function(
            self,
            "EvaluateDriftFunction",
            function_name=evaluate_drift_function_name,
            code=lambda_.Code.from_inline(lambda_evaluate_drift_code),
            role=lambda_role,
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_8,
            timeout=core.Duration.seconds(3),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
            },
        )

        sagemaker.CfnPipeline(
            self,
            "Pipeline",
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            pipeline_definition={
                "PipelineDefinitionS3Location": {
                    "Bucket": pipeline_definition_bucket,
                    "Key": pipeline_definition_key,
                }
            },
            role_arn=sagemaker_role_arn,
            tags=tags,
        )

        if drift_config is not None:
            # Create a CW alarm (which will be picked up by build pipeline)
            alarm_name = f"sagemaker-{pipeline_name}-threshold"
            cloudwatch.CfnAlarm(
                self,
                "DriftAlarm",
                alarm_name=alarm_name,
                alarm_description=f"Batch Drift Threshold",
                metric_name=drift_config.metric_name,
                threshold=drift_config.metric_threshold,
                namespace="aws/sagemaker/ModelBuildingPipeline/data-metrics",
                comparison_operator=drift_config.comparison_operator,
                dimensions=[
                    cloudwatch.CfnAlarm.DimensionProperty(
                        name="PipelineName", value=pipeline_name
                    ),
                ],
                evaluation_periods=drift_config.evaluation_periods,
                period=drift_config.period,
                datapoints_to_alarm=drift_config.datapoints_to_alarm,
                statistic=drift_config.statistic,
            )
