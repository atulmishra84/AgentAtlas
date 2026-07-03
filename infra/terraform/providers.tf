# AgentAtlas — AWS MVP Infrastructure
# Role: Senior Developer / Infra
# Scope: ECS Fargate + RDS, sized for testing/demo/MVP — not full HIPAA prod

terraform {
  required_version = ">= 1.7"
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state — created manually once before first apply:
  #   aws s3 mb s3://agentatlas-tfstate-<account_id>
  #   aws dynamodb create-table --table-name agentatlas-tf-lock \
  #     --attribute-definitions AttributeName=LockID,AttributeType=S \
  #     --key-schema AttributeName=LockID,KeyType=HASH \
  #     --billing-mode PAY_PER_REQUEST
  backend "s3" {
    bucket         = "agentatlas-tfstate-ACCOUNT_ID"  # replace at init time
    key            = "mvp/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "agentatlas-tf-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "AgentAtlas"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Stage       = "MVP"
    }
  }
}

# Note: 'random' provider used for password generation (rds.tf, ecs_cluster.tf)
