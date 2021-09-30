import boto3
import logging
import json
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)
sm_client = boto3.client("sagemaker")


def lambda_handler(event, context):
    if "TrainingJobName" in event:
        job_name = event["TrainingJobName"]
    else:
        raise KeyError("TrainingJobName not found for event: {}.".format(json.dumps(event)))

    # Get the training job
    response = sm_client.describe_training_job(TrainingJobName=job_name)
    status = response["TrainingJobStatus"]
    logger.info("Training job: {job_name} has status: {status}.")

    # Get the metrics as a dictionary
    metrics = {}
    for _, metric in enumerate(response["FinalMetricDataList"]):
        metrics[metric["MetricName"]] = metric["Value"]

    return {
        "statusCode": 200,
        "body": json.dumps({
            "TrainingJobName": job_name,
            "TrainingJobStatus": status,
            "TrainingMetrics": metrics,
        }),
    }