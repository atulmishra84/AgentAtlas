# AgentAtlas — AWS MVP Deployment

**Role:** Senior Developer
**Goal:** Get AgentAtlas running on real AWS infrastructure, fast enough to demo to stakeholders this week, solid enough to keep building on without a rewrite.

---

## Why these choices

This is explicitly an MVP/demo deployment, not the full HIPAA-grade build documented separately for Azure. Every decision below trades some production rigor for speed and cost, with a clear path to harden later. Where that trade-off was made, the Terraform comments call it out explicitly (`# MVP:` prefix) so nothing is a silent shortcut.

| Decision | MVP choice | Production path |
|---|---|---|
| Compute | ECS Fargate (mostly Spot) | Same — just shift Spot weight down |
| Database | Single-AZ RDS, `db.t4g.micro` | Flip `multi_az = true`, bump instance class |
| NAT | Single NAT Gateway | One per AZ for HA |
| Secrets | Secrets Manager, 0-day recovery | 30-day recovery window |
| TLS | Optional (HTTP works for demo) | Required, ACM + custom domain |
| State storage | In-memory Python dicts (existing backend) | RDS-backed persistence — see Phase 2 below |
| Backups | 3-day RDS retention, no final snapshot | 35-day PITR, final snapshot on destroy |
| CI/CD | Auto-deploy on push to `main` | Add staging gate + manual prod approval |

Estimated cost: **~$170–210/month** running continuously, or **~$0 between demos** if you run `teardown.sh` and `deploy.sh` around sessions (full redeploy takes ~10 minutes).

---

## What's in this package

```
aws_deploy/
├── docker/
│   ├── Dockerfile           # Multi-stage, non-root, healthcheck built in
│   ├── requirements.txt
│   └── main.py              # Copy of the validated v1.2 backend (100/100 security score)
├── terraform/
│   ├── providers.tf         # AWS + random providers, S3 remote state
│   ├── variables.tf         # All MVP-sized defaults — override via -var or tfvars
│   ├── networking.tf        # VPC, 2 AZs, 1 NAT Gateway, security groups
│   ├── rds.tf                # Single-AZ Postgres, Secrets Manager-backed credentials
│   ├── ecs_cluster.tf        # ECR, ECS cluster, IAM roles, log group
│   ├── ecs_service.tf        # ALB, target group, task def, service, autoscaling
│   └── outputs.tf            # Demo URL, alarms, SNS alerts
├── cicd/
│   └── deploy-aws.yml        # GitHub Actions: test → scan → deploy → smoke test
└── scripts/
    ├── deploy.sh              # First-time bootstrap (run manually, once)
    ├── teardown.sh            # Full destroy — use between demo sessions
    └── security_gate.py       # CI security regression check (validated: 100/100)
```

---

## Path to first demo (today)

### 1. One-time AWS setup
```bash
aws configure                     # if not already done
cd aws_deploy/scripts
chmod +x deploy.sh teardown.sh
./deploy.sh
```

This script bootstraps Terraform state, applies the infrastructure, builds and pushes the first container image, and runs a smoke test. It pauses for confirmation before `apply` and before pushing — review the plan output before approving.

Takes about 10–12 minutes end to end (RDS provisioning is the slow part, ~6 min).

### 2. What you get back

```
Demo URL:      http://agentatlas-mvp-xxxxx.us-east-1.elb.amazonaws.com/api/docs
Health check:  http://agentatlas-mvp-xxxxx.us-east-1.elb.amazonaws.com/health
Login:         admin / Admin@123
```

The `/api/docs` URL is Swagger UI — stakeholders can click through and try every endpoint live without you writing a separate demo script. That's the fastest way to make 40 working endpoints tangible to a non-technical audience.

### 3. Set up CI for ongoing iteration

Once the manual bootstrap works, wire up GitHub Actions so every push to `main` auto-deploys:

```bash
# Create the OIDC trust relationship (one-time)
aws iam create-role --role-name agentatlas-github-deploy \
  --assume-role-policy-document file://github-oidc-trust-policy.json
aws iam attach-role-policy --role-name agentatlas-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/PowerUserAccess  # scope down before prod

# Add to GitHub repo secrets:
#   AWS_ACCOUNT_ID = <your account id>
```

Then copy `cicd/deploy-aws.yml` into `.github/workflows/`. From that point, every merge to `main` runs the full pipeline: syntax check → smoke test → security gate (must score ≥85/100) → Trivy scan → build → push → deploy → post-deploy smoke test. If the security gate fails, the deploy never happens — this was deliberately built to catch the exact class of regression found during the earlier security testing pass (auth bypass, RBAC failures returning 500 instead of 403).

---

## Between demo sessions

```bash
./teardown.sh   # destroys everything, ~3 minutes
./deploy.sh     # stands it back up, ~10 minutes
```

Worth doing if there are days between stakeholder sessions — RDS and the NAT Gateway are the two line items that cost money even at zero traffic.

---

## Known gaps for this MVP stage (intentional, tracked)

1. **No persistent database wiring yet.** The backend currently uses in-memory Python dicts (`AGENTS_DB`, `CONNECTORS_DB`, etc.) — this Terraform provisions RDS Postgres so the next milestone is swapping those dicts for real queries, not standing up new infra. Until that swap happens, **every ECS task restart resets demo data to the seed set** — worth knowing before a live demo where you've been clicking around for 20 minutes.
2. **No custom domain by default.** `domain_name` variable is blank, so you get the raw ALB DNS name. Fine for internal demos; set the variable once there's a real domain to point at it (auto-provisions ACM cert + HTTPS listener).
3. **Default credentials are public knowledge** (`admin/Admin@123` is in this very README). Rotate via `POST /api/v1/users` before sharing the URL outside the immediate team.
4. **Single NAT Gateway** means if that AZ has an outage, outbound internet from ECS tasks in the other AZ briefly breaks (inbound via ALB stays fine — multi-AZ). Acceptable for MVP; the architecture supports adding a second NAT Gateway by changing one resource block when this graduates toward production.

---

## Rollback

If a deploy goes bad:
```bash
# Via GitHub Actions UI: "Run workflow" → set rollback_to_tag to the last known-good SHA
# Or manually:
aws ecs update-service --cluster agentatlas-mvp --service agentatlas-backend \
  --task-definition agentatlas-backend:<previous-revision-number> --force-new-deployment
```

The pipeline keeps the last 10 images in ECR (lifecycle policy in `ecs_cluster.tf`), so rollback targets are always available without rebuilding.
