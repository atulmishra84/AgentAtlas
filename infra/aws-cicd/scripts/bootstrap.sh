#!/bin/bash
# AgentAtlas — CI/CD Bootstrap
# Deploys all three CloudFormation stacks in the correct dependency order.
# Run once, manually, after the Terraform ECS/ECR infrastructure is up.
# After this runs, every push to the configured GitHub branch auto-deploys.

set -euo pipefail

# ── Prereq checks ─────────────────────────────────────────────────────────
command -v aws   >/dev/null || { echo "AWS CLI not found"; exit 1; }
command -v jq    >/dev/null || { echo "jq not found — brew/apt install jq"; exit 1; }

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
  echo "AWS credentials not configured. Run: aws configure"
  exit 1
}
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
echo "Account: $ACCOUNT_ID  Region: $REGION"
echo ""

# ── Required inputs ────────────────────────────────────────────────────────
# These come from Terraform outputs — run `terraform output` in aws_deploy/terraform/
# to get the values, then paste them here or set as env vars.

GITHUB_OWNER="${GITHUB_OWNER:-}"
GITHUB_REPO="${GITHUB_REPO:-agentatlas}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
CODESTAR_CONNECTION_ARN="${CODESTAR_CONNECTION_ARN:-}"
NOTIFICATION_EMAIL="${NOTIFICATION_EMAIL:-platform-team@veliqhq.com}"
ENVIRONMENT="${ENVIRONMENT:-mvp}"
PROJECT_NAME="${PROJECT_NAME:-agentatlas}"

# From Terraform outputs:
ECS_CLUSTER="${ECS_CLUSTER:-}"        # terraform output -raw ecs_cluster_name
ECS_SERVICE="${ECS_SERVICE:-}"        # terraform output -raw ecs_service_name
ECR_REPO_URI="${ECR_REPO_URI:-}"      # terraform output -raw ecr_repository_url
ALB_DNS="${ALB_DNS:-}"                # terraform output -raw alb_dns_name

# ALB listener and target group ARNs (from ALB console or AWS CLI)
ALB_LISTENER_ARN="${ALB_LISTENER_ARN:-}"
TG_BLUE_NAME="${TG_BLUE_NAME:-}"
TG_GREEN_NAME="${TG_GREEN_NAME:-${TG_BLUE_NAME}-green}"

# ── Validate required inputs ───────────────────────────────────────────────
MISSING=()
for var in GITHUB_OWNER CODESTAR_CONNECTION_ARN ECS_CLUSTER ECS_SERVICE ECR_REPO_URI ALB_DNS ALB_LISTENER_ARN TG_BLUE_NAME; do
  if [ -z "${!var}" ]; then
    MISSING+=("$var")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "Missing required env vars:"
  for v in "${MISSING[@]}"; do echo "  $v"; done
  echo ""
  echo "Set them in your shell or create a .env file and source it:"
  echo "  source .env && ./bootstrap.sh"
  echo ""
  echo "CODESTAR_CONNECTION_ARN: create a GitHub connection in the console at:"
  echo "  https://console.aws.amazon.com/codesuite/settings/connections"
  echo "  Then approve it from your GitHub account."
  exit 1
fi

STACK_PREFIX="${PROJECT_NAME}-${ENVIRONMENT}"

echo "=== Step 1/3: Deploy pipeline stack ==="
aws cloudformation deploy \
  --stack-name "${STACK_PREFIX}-pipeline" \
  --template-file cfn/pipeline.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName="$PROJECT_NAME" \
    Environment="$ENVIRONMENT" \
    GitHubOwner="$GITHUB_OWNER" \
    GitHubRepo="$GITHUB_REPO" \
    GitHubBranch="$GITHUB_BRANCH" \
    GitHubConnectionArn="$CODESTAR_CONNECTION_ARN" \
    ECSClusterName="$ECS_CLUSTER" \
    ECSServiceName="$ECS_SERVICE" \
    ECRRepositoryUri="$ECR_REPO_URI" \
    ALBListenerArn="$ALB_LISTENER_ARN" \
    ALBTargetGroupBlueName="$TG_BLUE_NAME" \
    ALBTargetGroupGreenName="$TG_GREEN_NAME" \
    NotificationEmail="$NOTIFICATION_EMAIL" \
  --tags Project="$PROJECT_NAME" Environment="$ENVIRONMENT" ManagedBy=CloudFormation

PIPELINE_OUTPUTS=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_PREFIX}-pipeline" \
  --query "Stacks[0].Outputs" --output json)

NOTIFICATION_TOPIC=$(echo "$PIPELINE_OUTPUTS" | \
  jq -r '.[] | select(.OutputKey=="NotificationTopicArn") | .OutputValue')
PIPELINE_URL=$(echo "$PIPELINE_OUTPUTS" | \
  jq -r '.[] | select(.OutputKey=="PipelineUrl") | .OutputValue')

echo "Pipeline stack deployed"
echo "  Pipeline URL: $PIPELINE_URL"
echo "  Notification topic: $NOTIFICATION_TOPIC"
echo ""

echo "=== Step 2/3: Deploy hooks stack (smoke test Lambda) ==="
aws cloudformation deploy \
  --stack-name "${STACK_PREFIX}-hooks" \
  --template-file cfn/hooks.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName="$PROJECT_NAME" \
    Environment="$ENVIRONMENT" \
    ALBDnsName="$ALB_DNS" \
    TestListenerPort="8080"

HOOK_LAMBDA_ARN=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_PREFIX}-hooks" \
  --query "Stacks[0].Outputs[?OutputKey=='SmokeTestLambdaArn'].OutputValue" \
  --output text)

echo "Hooks stack deployed"
echo "  Smoke test Lambda ARN: $HOOK_LAMBDA_ARN"
echo ""

# Update appspec.yml with the actual Lambda ARN
sed -i.bak "s|LambdaFunctionToCallAfterAllowTestTraffic|${HOOK_LAMBDA_ARN}|g" \
  appspec/appspec.yml
echo "Updated appspec.yml with Lambda ARN"
echo ""

echo "=== Step 3/3: Deploy observability stack (alarms + dashboard) ==="
aws cloudformation deploy \
  --stack-name "${STACK_PREFIX}-cicd-obs" \
  --template-file cfn/observability.yml \
  --parameter-overrides \
    ProjectName="$PROJECT_NAME" \
    Environment="$ENVIRONMENT" \
    PipelineName="${STACK_PREFIX}" \
    ECSClusterName="$ECS_CLUSTER" \
    ECSServiceName="$ECS_SERVICE" \
    NotificationTopicArn="$NOTIFICATION_TOPIC"

DASHBOARD_URL=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_PREFIX}-cicd-obs" \
  --query "Stacks[0].Outputs[?OutputKey=='CICDDashboardUrl'].OutputValue" \
  --output text)

echo "Observability stack deployed"
echo "  Dashboard: $DASHBOARD_URL"
echo ""

echo "======================================================"
echo "CI/CD BOOTSTRAP COMPLETE"
echo ""
echo "Pipeline: $PIPELINE_URL"
echo "Dashboard: $DASHBOARD_URL"
echo ""
echo "Next: push a commit to ${GITHUB_BRANCH} on ${GITHUB_OWNER}/${GITHUB_REPO}"
echo "The pipeline will trigger automatically within 30 seconds."
echo ""
echo "First pipeline run will:"
echo "  1. Run pytest (17 tests)"
echo "  2. Build and push Docker image to ECR"
echo "  3. Boot the image, run 22-check security gate (must score 95+)"
echo "  4. Pause for manual approval (check your email: ${NOTIFICATION_EMAIL})"
echo "  5. Blue/green deploy via CodeDeploy to ECS"
echo "  6. Run smoke test Lambda against the green task set"
echo "  7. Shift production traffic if smoke tests pass"
echo "  8. Terminate the blue task set 5 minutes after successful traffic shift"
echo "======================================================"
