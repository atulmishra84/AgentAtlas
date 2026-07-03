# AgentAtlas

Enterprise AI agent discovery and monitoring platform by **VeliqHQ**.

Discovers, inventories, and monitors every AI agent across your cloud, endpoint, and SaaS estate — including shadow AI running on employee laptops that never appears in any cloud console.

---

## What's in this repository

```
├── app/                        # FastAPI backend (Python 3.12)
│   ├── main.py                 # 40 API endpoints, JWT auth, RBAC
│   ├── database.py             # SQLAlchemy Core + async engine
│   ├── repositories.py         # Repository pattern, tenant isolation
│   ├── seed.py                 # Idempotent seed data (9 agents, 7 connectors)
│   ├── Dockerfile              # Multi-stage, non-root, exec-form CMD
│   ├── requirements.txt        # Pinned production dependencies
│   ├── requirements-dev.txt    # Test + lint dependencies
│   ├── pytest.ini
│   ├── security_gate.py        # 22-check CI security regression suite
│   ├── smoke_test.py           # Post-deploy smoke test (6 checks)
│   └── tests/test_api.py       # 17 pytest tests (17/17 passing)
│
├── frontend/                   # React 18 dashboard
│   ├── src/App.jsx             # 2034-line single-file app (all 4 weeks)
│   ├── package.json
│   ├── vite.config.js
│   └── index.html
│
├── infra/
│   ├── terraform/              # AWS ECS Fargate + RDS + ECR (MVP)
│   ├── k8s/                    # Kubernetes (Kustomize, staging + production)
│   ├── helm/agentatlas/        # Helm chart alternative
│   └── aws-cicd/               # AWS native CI/CD (CodePipeline + CodeBuild + CodeDeploy)
│       ├── buildspecs/         # CodeBuild build + security gate specs
│       ├── cfn/                # CloudFormation: pipeline, hooks, observability
│       ├── appspec/            # CodeDeploy ECS blue/green appspec
│       └── scripts/            # Bootstrap, Lambda hook, task def generator
│
├── monitoring/
│   ├── prometheus/             # Scrape config + 11 alert rules (promtool validated)
│   └── grafana/dashboards/     # 10-panel production dashboard
│
└── docs/
    ├── ARCHITECTURE_SUMMARY.md
    ├── PRODUCTION_CHECKLIST.md
    └── AWS_DEPLOY.md
```

---

## Quick start (local dev)

```bash
# Backend
cd app
pip install -r requirements.txt -r requirements-dev.txt
DATABASE_URL="sqlite+aiosqlite:///./dev.db" uvicorn main:app --port 8215 --reload

# Test
pytest tests/ -v

# Security gate
python security_gate.py --port 8215 --min-score 95

# Frontend (separate terminal)
cd frontend
npm install
npm run dev          # → http://localhost:5173
```

**Demo credentials:** `admin / Admin@123` · `analyst / Analyst@123`

---

## Deploy to AWS (ECS Fargate)

### Step 1 — Provision infrastructure with Terraform

```bash
cd infra/terraform

# One-time state backend bootstrap
aws s3 mb s3://agentatlas-tfstate-$(aws sts get-caller-identity --query Account --output text)
aws dynamodb create-table --table-name agentatlas-tf-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Update providers.tf with your account ID, then:
terraform init
terraform apply
```

Terraform creates: VPC, ECS Fargate cluster, ECR repository, ALB, RDS Postgres, Secrets Manager secrets, CloudWatch log group.

### Step 2 — Bootstrap the CI/CD pipeline

```bash
# Set required env vars (values from terraform output)
export GITHUB_OWNER=your-org
export GITHUB_REPO=agentatlas
export GITHUB_BRANCH=main
export CODESTAR_CONNECTION_ARN=arn:aws:codestar-connections:...
export ECS_CLUSTER=$(terraform -chdir=infra/terraform output -raw ecs_cluster_name)
export ECS_SERVICE=$(terraform -chdir=infra/terraform output -raw ecs_service_name)
export ECR_REPO_URI=$(terraform -chdir=infra/terraform output -raw ecr_repository_url)
export ALB_DNS=$(terraform -chdir=infra/terraform output -raw alb_dns_name)
export ALB_LISTENER_ARN=<from console>
export TG_BLUE_NAME=<from console>

chmod +x infra/aws-cicd/scripts/bootstrap.sh
./infra/aws-cicd/scripts/bootstrap.sh
```

After bootstrap, every push to `main` triggers the pipeline automatically:

1. pytest (17 tests)
2. Docker build + ECR push
3. Security gate (must score ≥ 95/100)
4. Manual approval (email notification)
5. CodeDeploy blue/green deploy to ECS
6. Smoke test Lambda against green task set
7. Traffic shift if tests pass · automatic rollback if they fail

---

## Deploy to Kubernetes

```bash
# Staging
kubectl apply -k infra/k8s/overlays/staging

# Production
kubectl apply -k infra/k8s/overlays/production

# Or via Helm
helm upgrade --install agentatlas infra/helm/agentatlas \
  --set image.tag=$(git rev-parse --short HEAD) \
  --namespace agentatlas --create-namespace
```

---

## Monitoring

| What | Where |
|------|-------|
| Prometheus scrape | `monitoring/prometheus/prometheus.yml` |
| Alert rules (11) | `monitoring/prometheus/agentatlas-alerts.yml` |
| Grafana dashboard | `monitoring/grafana/dashboards/agentatlas-overview.json` |
| Metrics endpoint | `GET /metrics` (Prometheus format) |
| Liveness probe | `GET /healthz` |
| Readiness probe | `GET /readyz` |

---

## Security

- JWT HS256 with algorithm-whitelist (none-algorithm blocked)
- RBAC: `admin` and `read_only` roles enforced on all mutating endpoints
- Tenant isolation: structural `tenant_id` as first arg on all repository methods
- Security gate: 22 automated checks on every CI build
- All secrets from AWS Secrets Manager — nothing in code or environment variables

**Validated score: 100/100** (22/22 checks passing against live server)

---

## Cost (AWS ECS MVP)

~$170–210/month continuous. ~$0 between sessions using `./infra/aws-cicd/scripts/teardown.sh`.

---

## Built by VeliqHQ

Enterprise AI governance infrastructure. Contact: hello@veliqhq.com
