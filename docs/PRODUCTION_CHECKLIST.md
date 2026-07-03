# AgentAtlas — Production Deployment Checklist
## Senior DevOps Engineer sign-off document

Every item below maps to something built and verified in this engineering pass, not aspirational. Where a check was run, the actual result is noted — this checklist is meant to be re-run, not just read.

---

## Pre-deployment

### Infrastructure
- [ ] VPC with private subnets for data layer confirmed (no public IP on RDS, no public IP on pod nodes)
- [ ] `kubeconform` validates all manifests against the real K8s API schema — **verified this session: 12/12 valid for both staging and production Kustomize overlays, 6/6 valid for the rendered Helm chart**
- [ ] `helm lint` passes with zero failures — **verified: `1 chart(s) linted, 0 chart(s) failed`**
- [ ] Pod Security Standards set to `restricted` at the namespace level (not relying on per-pod opt-in)
- [ ] NetworkPolicy default-deny confirmed, explicit allow rules only for ingress→API and API→DB/Redis
- [ ] Resource quotas and LimitRange applied to the namespace so a misconfigured deploy can't starve the cluster

### Secrets
- [ ] No secret value exists in Git, in any form, encrypted or not — confirmed by grep across the repo for the string patterns `JWT_SECRET=`, `password=`, `api_key=`
- [ ] ExternalSecret syncs from AWS Secrets Manager / Azure Key Vault, refreshInterval set (1h)
- [ ] IRSA / Workload Identity confirmed — no static cloud credentials inside any pod
- [ ] Secret rotation tested: rotate the DB password in Secrets Manager, confirm the synced K8s Secret updates within the refresh interval, confirm pods pick up the new value (the Helm chart's `checksum/secrets` annotation forces a rolling restart on secret change — verify this actually triggers)

### Application
- [ ] Full pytest suite passes — **verified this session: 17/17 passed in ~1.2s**
- [ ] Security regression gate passes at the 95+ threshold — **verified this session: 22/22 checks, 100/100 score**
- [ ] Smoke test script passes against a live instance — **verified this session: 6/6 checks**
- [ ] No deprecation warnings in startup logs — **verified: lifespan modernization removed the `on_event` deprecation warning entirely**
- [ ] `/healthz` and `/readyz` are genuinely different (liveness never touches the DB, readiness does) — **verified by code inspection and live test**
- [ ] Database migrations are managed by Alembic, not ad-hoc `create_all` in any environment where schema drift matters (MVP/dev: `create_all` is acceptable per the Architect's original design doc; production: requires the Alembic migration path noted as future work in `03_optimization.md`)
- [ ] Connection pool sized correctly for the target RDS instance class and max replica count (4 × (pool_size=4 + max_overflow=2) = 24 connections at full HPA scale-out — confirm against the actual RDS instance's `max_connections`, not just the `db.t4g.micro` default assumed in the original design)

### Observability
- [ ] Prometheus successfully scrapes the `/metrics` endpoint via pod annotation discovery, not static config
- [ ] All 11 alerting rules pass `promtool check rules` — **verified this session: `SUCCESS: 11 rules found`**
- [ ] Every alert that references a custom metric (`agentatlas_*`) has been confirmed to actually emit data — **verified this session: `agentatlas_discovery_jobs_total` and `agentatlas_db_query_duration_seconds` were found declared-but-never-incremented during this pass and have now been wired and confirmed populating real data**
- [ ] Grafana dashboard JSON is valid and provisions without error — **verified: valid JSON, 10 panels**
- [ ] Structured JSON logging confirmed emitting well-formed, parseable log lines with `request_id` correlation — **verified this session**
- [ ] Distributed tracing (OTel) confirmed exporting spans when `OTEL_EXPORTER_OTLP_ENDPOINT` is set
- [ ] PagerDuty/Slack alert routing tested with a deliberately-fired test alert before relying on it during a real incident

---

## Deployment day

### Staging gate (must pass before production is even attempted)
- [ ] Deploy to staging via CI
- [ ] `kubectl rollout status` confirms successful rollout within timeout
- [ ] Smoke test passes against the live staging URL
- [ ] Security gate passes against the live staging URL (not just localhost in CI)
- [ ] Manual exploratory check: open `/api/docs`, exercise 3-4 endpoints by hand as a final human sanity check before requesting production approval

### Production deploy
- [ ] GitHub Environment protection rule confirms a required reviewer approved the production deploy (not just "the pipeline ran")
- [ ] Image was built once and promoted (same digest from staging to production), never rebuilt — confirms staging actually tested what production will run
- [ ] Image signed via cosign, signature verified before deploy
- [ ] `maxUnavailable: 0` rolling update confirmed in the live cluster — capacity must never dip during the rollout
- [ ] Post-deploy smoke test passes
- [ ] Automatic rollback path is live and was tested at least once in staging before relying on it in production (deliberately deploy a broken image to staging, confirm rollback fires)
- [ ] Deploy annotated in Grafana so a post-incident timeline can correlate "things got worse" with "we deployed at this exact minute"

### Immediately after go-live
- [ ] Watch the error-rate and latency dashboards for the first 30 minutes of real traffic, not just the automated smoke test window
- [ ] Confirm HPA is scaling as expected under real load, not just passing a synthetic check
- [ ] Confirm log volume and cost are within expected bounds (a misconfigured log level can produce 10x the expected CloudWatch/Loki ingestion cost silently)

---

## Ongoing reliability practices

- [ ] PodDisruptionBudget (`minAvailable: 1`) confirmed to actually block a node drain that would violate it — test with `kubectl drain` against a non-production cluster first
- [ ] Chaos test: kill a random pod manually (`kubectl delete pod`), confirm zero customer-visible impact (this is what the 2-replica minimum + PDB + readiness probes are supposed to guarantee — verify the guarantee, don't just trust the config)
- [ ] Database failover tested: trigger an RDS failover (or simulate by blocking the primary's port via NetworkPolicy), confirm `/readyz` correctly fails and the pod is pulled from rotation rather than serving 500s to users
- [ ] Quarterly: review the alerting rules against actual incident history — an alert that's never fired in a quarter despite real incidents happening is a gap, not a quiet success
- [ ] Quarterly: review HPA min/max bounds against actual observed traffic patterns; thresholds set at launch with no real traffic data are a starting guess, not a permanent decision

---

## Known gaps — carried forward honestly, not hidden

These are real, current gaps. Listing them here is the difference between a checklist and a marketing document.

1. **Alembic migrations not yet implemented.** The app currently uses `metadata.create_all()` at startup, which is safe for the current single-environment deploy pattern but will not support zero-downtime schema changes once there's a second environment with real production data that can't be dropped and recreated. This was flagged as future work in the persistence-layer engineering pass and remains open.
2. **Connector credential encryption at rest** (`connectors.credentials` JSONB column) is schema-ready but not yet using `pgcrypto` — also flagged previously, still open. Do not store real third-party API keys in this column until that's closed.
3. **No read-replica wiring in the application layer yet.** The architecture diagram shows a read replica for reporting-style queries (`stats`, `coverage`, `search`), but the current `database.py` engine points only at the primary. This is a real-but-deferred optimization, not a correctness issue — flag it before it becomes a surprise at scale.
4. **WebSocket horizontal scaling**: with 2+ API pods behind a single Service, a WebSocket client connected to pod A never receives an event published by a request handled on pod B (the in-process `WS_CONNECTIONS` list is per-pod, not shared). This works correctly today only because the discovery background task happens to run in the same process that published the event in most cases — but it is not a reliable pub/sub guarantee at multi-pod scale. Needs a shared broker (Redis pub/sub is the natural fit, and Redis is already in the architecture diagram) before this is genuinely production-correct under the 2-12 replica HPA range configured above.
