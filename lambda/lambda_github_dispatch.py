import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import json
import os
import logging
from urllib.request import Request, urlopen


LOG_LEVEL = os.getenv("LOG_LEVEL", "MAIN").upper()

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)
config = Config(retries={"max_attempts": 10, "mode": "standard"})
secrets = boto3.client("secretsmanager")


def get_github_access_token(secret_id: str):
    response = secrets.get_secret_value(SecretId=secret_id)
    return json.loads(response["SecretString"])


def post_github(url: str, token: str, body: dict):
    """Post to github so that we can trigger a workflow
    see: https://docs.github.com/en/actions/learn-github-actions/events-that-trigger-workflows#workflow_dispatch

    Args:
        url (str): Github url for repo
        token (str): Github personal access token
        body (dict): The payload to post to Github

    Returns:
        [tuple(int, str)]: Returns a tuple of the HTTP status code, and body as text
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    postdata = json.dumps(body).encode()
    logging.info(f"POST url: {url}")
    httprequest = Request(url, headers=headers, data=postdata, method="POST")
    with urlopen(httprequest) as response:
        text = response.read().decode()
        logging.info(f"Response: {response.status}")
        logging.debug(text)
        return response.status, text


def lambda_handler(event: dict, context: dict):
    """This lambda will call the dispatch workflow event

    Args:
        event ([dict]): GitHub params with either EventType, or Branch and Workflow
            {
                "SecretId": "GitHubToken",
                "Repo": "GitHubRepo",
                "EventType": "build",
                "Branch": "main",
                "Workflow": "build.yml",
            }
        context ([dict]): [description]

    Returns:
        [dict]: Returns the statusCode and Body of the GithUb actions response
    """
    # Get the secret that contains github user and token
    access_token = get_github_access_token(event["SecretId"])
    username = access_token["user"]
    token = access_token["token"]
    # Build up the url
    repo = event["Repo"]
    event_type = event.get("EventType")
    branch = event.get("Branch")
    workflow = event.get("Workflow")
    if event_type:
        # Call repository event for default branch
        url = f"https://api.github.com/repos/{username}/{repo}/dispatches"
        status_code, text = post_github(url, token, {"event_type": event_type})
    elif workflow and branch:
        # Call the workflow for specific branch
        url = f"https://api.github.com/repos/{username}/{repo}/actions/workflows/{workflow}/dispatches"
        status_code, text = post_github(url, token, {"ref": branch})
    else:
        raise Exception("Require EventType or Workflow")
    return {"statusCode": status_code, "body": text}
