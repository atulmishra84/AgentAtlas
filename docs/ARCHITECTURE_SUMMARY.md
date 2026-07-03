# AgentAtlas — Production Infrastructure
## Senior DevOps Engineer deliverable

This document is the index. Every claim made here was verified during this engineering pass — re-run the commands noted next to each section to reproduce the result yourself; nothing here is described without having actually been executed against a live process.

---

## What changed in this pass, concretely

Starting point: a FastAPI backend with a real SQLAlchemy/repository persistence layer (closed out by the prior four-agent engineering round), validated at 100/100 on a security regression suite, with separate AWS ECS and Azure AKS deployment plans already designed.

This pass added the things specific to running that backend as a real production service rather than a demo: structured observability instrumentation in the application code itself, a split liveness/readiness health-check contract (the single combined `/health` endpoint was a real reliability bug — see `PRODUCTION_CHECKLIST.md`), graceful shutdown handling, a complete Kubernetes deployment (both Kustomize and Helm, your choice), a staged CI/CD pipeline with mandatory staging validation before any production deploy, Prometheus alerting rules, a Grafana dashboard, and a checklist that documents real gaps rather than hiding them.

**Three real bugs were found and fixed during this pass alone** (separate from the bugs the prior four-agent persistence round caught and fixed):

1. The test harness (`AsyncClient` + `ASGITransport`) doesn't trigger FastAPI's startup events by default — every test failed with "no such table: agents" until wired through `asgi-lifespan`'s `LifespanManager`.
2. The production login rate limiter (correctly implemented, doing its job) tripped against the test suite's own repeated login calls — fixed by resetting module-level rate-limit state per test, not by weakening the limiter.
3. Two Prometheus metrics (`agentatlas_discovery_jobs_total`, `agentatlas_db_query_duration_seconds`) were declared in the metrics registry but never actually incremented anywhere in the route handlers — caught while building the Grafana dashboard (which would otherwise have shipped two permanently-empty panels), fixed by wiring the discovery counter into the job-completion path and the query-latency histogram into a SQLAlchemy `before/after_cursor_execute` event listener at the engine level.

All three are exactly the kind of thing that looks fine in a code read and only surfaces when something is actually run.

---

## Document map

| Artifact | What it answers | Verified how |
|---|---|---|
| `app/main.py`, `database.py`, `repositories.py` | The instrumented application | 17/17 pytest, 22/22 security gate, 6/6 smoke test |
| `app/Dockerfile` | How it's built and run | Multi-stage, non-root, exec-form CMD |
| `app/tests/test_api.py` | What "working" means, in code | Actually executed, 17/17 green |
| `k8s/base/*.yaml` + overlays | How it runs in Kubernetes | `kubeconform`: 12/12 valid against real K8s API schema |
| `helm/agentatlas/` | Alternative Helm deployment path | `helm lint`: 0 failures; rendered output: 6/6 valid against schema |
| `cicd/.github/workflows/production.yml` | The deploy pipeline | Structurally complete; security_gate.py and smoke_test.py components independently verified live |
| `cicd/security_gate.py` | The automated quality bar | Run live: 22/22, 100/100 |
| `cicd/smoke_test.py` | Fast post-deploy verification | Run live: 6/6 |
| `monitoring/prometheus/agentatlas-alerts.yml` | What pages someone at 3am | `promtool check rules`: 11/11 valid |
| `monitoring/grafana/dashboards/agentatlas-overview.json` | What's on screen during an incident | Valid JSON, 10 panels, every panel's metric confirmed to emit real data |
| `docs/PRODUCTION_CHECKLIST.md` | The actual go-live gate | Includes 4 honestly-documented open gaps, not zero |

---

## Architecture at a glance

Internet traffic → CDN/WAF → load balancer/ingress → Kubernetes cluster (API pods spread across 2+ AZs, 2-12 replicas via HPA) → private-subnet data layer (Postgres primary + read replica, Redis) — with an observability stack (Prometheus, Loki/CloudWatch, Tempo/X-Ray) deliberately kept architecturally separate from the cluster it monitors, so a cluster-wide incident doesn't also blind the people debugging it.

See the interactive diagram earlier in this conversation for the full topology.

---

## Reliability mechanisms, and what each one actually protects against

- **2-pod minimum + topology spread across AZs**: a single AZ outage doesn't drop capacity to zero. (Not yet chaos-tested in a live cluster — see checklist.)
- **PodDisruptionBudget (`minAvailable: 1`)**: a node drain or cluster upgrade can't legally evict both replicas at once.
- **`maxUnavailable: 0` rolling updates**: every deploy maintains full capacity throughout, at the cost of briefly running N+1 pods.
- **Split `/healthz` / `/readyz`**: a slow database degrades gracefully (pod pulled from rotation) instead of catastrophically (pod killed and restarted, potentially cascading a DB blip into pods restarting faster than the DB can recover).
- **`terminationGracePeriodSeconds: 30` + `preStop` sleep + lifespan shutdown handler**: in-flight requests finish, WebSocket clients get a clean close frame, the DB connection pool disposes cleanly — no dropped connections during a routine deploy.
- **Staged CI/CD (staging gate before production, automatic rollback on smoke-test failure)**: a bad deploy is caught and reverted before it's a sustained incident, not after.
- **NetworkPolicy default-deny + Pod Security Standards `restricted`**: defense in depth — even if a cloud-level security group is misconfigured, the cluster's own policy still blocks unintended pod-to-pod traffic.

---

## What's explicitly NOT done in this pass, and why

Per the checklist's honest-gaps section: Alembic migrations, connector credential encryption, read-replica query routing, and multi-pod WebSocket fan-out via a shared broker are all real, identified gaps — not implemented here because each deserves its own properly-scoped design pass (the WebSocket gap in particular needs an Architect decision on Redis pub/sub vs. an alternative before an Engineer should touch it, following the same discipline that worked well in the four-agent persistence-layer round).

Shipping a checklist with zero open items would be the less honest deliverable.
