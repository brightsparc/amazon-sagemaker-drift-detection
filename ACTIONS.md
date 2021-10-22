# AWS SageMaker Workflow for GitHub Actions

This template repository contains a sample application and sample GitHub Actions workflow files for continuously deploying both application code and infrastructure as code with GitHub Actions.

This MLOps workflow demonstrates training and evaluating a machine learning model to predict taxi fare from the public [New York City Taxi dataset](https://registry.opendata.aws/nyc-tlc-trip-records-pds/) deployed with Amazon SageMaker. 

This repository contains a number of start workflow files for GitHub Actions:
1. [build-deploy-pipeline.yml](.github/workflows/build-deploy-pipeline.yml) This workflow runs when a pull request is opened or pushed to the `main` branch (see below).
1. [publish-template.yml](.github/workflows/publish-template.yml) runs when a new commit is pushed to the main branch in the `aws` environment.

## Create a GitHub repository from this template

Click the "Use this template" button above to create a new repository from this template.

Clone your new repository, and deploy the IAM resources needed to enable GitHub Actions to deploy CloudFormation templates:

```
aws cloudformation deploy \
  --stack-name amazon-sagemaker-workflow-for-github-actions \
  --template-file cloudformation/github-actions-setup.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```
You can review the permissions that your repository's GitHub Actions deployment workflow will have in the [github-actions-setup.yml](cloudformation/github-actions-setup.yml) CloudFormation template.

Retrieve the IAM access key credentials that GitHub Actions will use for deployments:
```
aws secretsmanager get-secret-value \
  --secret-id github-actions-sagemaker \
  --region us-east-1 \
  --query SecretString \
  --output text
```

### Build Deploy Pipeline

This sample includes a `Build and Deploy` [GitHub Actions](https://docs.github.com/en/actions/learn-github-actions/understanding-github-actions) workflow with contains the following jobs
1. The `Build Model` job will create or update a SageMaker Model Build Pipeline using AWS CloudFormation.
2. The `Batch` jobs will create or update a SageMaker Pipeline to run Batch Scoring for Staging and Production environments.
3. The `Deploy` jobs will deploy SageMaker Endpoints to Staging and Production environments.

These jobs are configured to run against a specific [environment](https://docs.github.com/en/actions/reference/environments) which contains both secrets and optional *protection rules*.

![Execution Role](docs/github-actions-workflow.png)

### Environments

1. `development` environment in which runs your `Build Model` job and starts the SageMaker pipeline execution.  On completion this pipeline will publish a model to the Registry.  It is recommend you run this on `pull_request` and `push` events.
2. `staging` and `batch-staging` environments will enable you to run the `Batch` and `Deploy` jobs respectively in staging.
  * You should configure a *protection rule* for data science team so this job is delayed until the latest model has been approved in the SageMaker model registry.
  3. `prod` and `batch-prod` environments will enable you to run the `Batch` and `Deploy` jobs respectively in production.
  * You should configure a *protection rule* for your operations team which will approve this only once they are happy that the staging environment has been tested.

For each of the environments you will require setting up the following secrets.
1. Create a secret named `AWS_ACCESS_KEY_ID` containing the `AccessKeyId` value returned above.
1. Create a secret named `AWS_SECRET_ACCESS_KEY` containing in the `SecretAccessKey` value returned above.
1. Create a secret named `AWS_SAGEMAKER_ROLE` containing the ARN for the `AmazonSageMakerServiceCatalogProductsUseRole` in your account.

When the workflow successfully completes, drift detection is configured to trigger re-training on drift detection in the production batch pipeline or real-time endpoint.

### GitHub Dispatch Events

Create a [personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token) for your GitHub users with `repo` scope and `actions:write` permissions to enable you to send a [workflow dispatch](https://docs.github.com/en/rest/reference/actions#create-a-workflow-dispatch-event) event.

## Testing

You can test the pipeline with a github repository that has the same name as your SageMaker Project.

Export the environment variables for the `SAGEMAKER_PROJECT_NAME` and `SAGEMAKER_PROJECT_ID` created by your SageMaker Project cloud formation.

Also pass the `GITHUB_USER` and `GITHUB_TOKEN` from the personal access token created above.

Then run the `python` command:

```
export SAGEMAKER_PROJECT_NAME=<<existing-project-name>>
export SAGEMAKER_PROJECT_ID=<<existing-project-id>>
export GITHUB_USER=<<your-github-username>>
export GITHUB_TOKEN=<<your-personal-token>>
cdk deploy github-actions -c drift:ProductsUseRoleName="" \
    --parameters SageMakerProjectName=$SAGEMAKER_PROJECT_NAME \
    --parameters SageMakerProjectId=$SAGEMAKER_PROJECT_ID \
    --parameters GitHubUser=$GITHUB_USER \
    --parameters GitHubToken=$GITHUB_TOKEN
```

You can verify your secret for your GitHub action has been created by getting its value

```
aws secretsmanager get-secret-value \
  --secret-id "sagemaker-<<existing-project-id>>-github-action" \
  --region us-east-1 \
  --query SecretString \
  --output text
```