"""
AgentAtlas — CodeDeploy lifecycle hook Lambda
Hook: AfterAllowTestTraffic

CodeDeploy calls this function after it shifts the test listener (port 8080)
to the green task set, but before it shifts the production listener (port 80/443).
If this function calls PutLifecycleEventHookExecutionStatus with status=Failed,
CodeDeploy rolls back automatically — the green set is terminated and the blue
set keeps all production traffic.

This is the automated gate between "new code is running" and "users hit new code".

Deploy to: us-east-1, same account as the ECS cluster.
Runtime: python3.12
Timeout: 120s (smoke tests need ~30s; give headroom for cold start + retries)
Memory: 128 MB (pure network I/O, no compute)
Required env vars:
  TEST_LISTENER_PORT  — port the ALB test listener is on (default 8080)
  ALB_DNS_NAME        — ALB DNS name (set from SSM or Terraform output)
  CODEDEPLOY_REGION   — AWS region
"""
import json
import os
import time
import urllib.error
import urllib.request

import boto3

codedeploy = boto3.client(
    "codedeploy",
    region_name=os.environ.get("CODEDEPLOY_REGION", "us-east-1")
)

ALB_DNS      = os.environ.get("ALB_DNS_NAME", "")
TEST_PORT    = int(os.environ.get("TEST_LISTENER_PORT", "8080"))
BASE_URL     = f"http://{ALB_DNS}:{TEST_PORT}"


def req(path, method="GET", body=None, token=None):
    url = BASE_URL + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def run_smoke_tests():
    """
    Focused smoke test against the green task set.
    Six checks — deliberately fast, not exhaustive. The full security gate
    already ran in the CodeBuild stage before this deployment started.
    """
    results = []

    def chk(name, ok):
        results.append((name, ok))
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")

    # 1. Liveness (just the process — does not touch DB)
    deadline = time.time() + 60
    live = False
    while time.time() < deadline:
        try:
            code, _ = req("/healthz")
            if code == 200:
                live = True
                break
        except Exception:
            pass
        time.sleep(3)
    chk("Liveness check (/healthz)", live)

    # 2. Readiness (DB connection confirmed)
    try:
        code, _ = req("/readyz")
        chk("Readiness check (/readyz)", code == 200)
    except Exception as e:
        chk(f"Readiness check (/readyz) — {e}", False)

    # 3. Auth endpoint reachable and returns a token
    try:
        code, body = req(
            "/api/v1/auth/login",
            method="POST",
            body={"username": "admin", "password": "Admin@123"}
        )
        token = body.get("access_token", "")
        chk("Login returns access token", code == 200 and bool(token))
    except Exception as e:
        token = ""
        chk(f"Login — {e}", False)

    # 4. Protected endpoint returns data (not 401 or 500)
    if token:
        try:
            code, body = req("/api/v1/agents/stats", token=token)
            chk("Stats endpoint returns data", code == 200 and "total" in body)
        except Exception as e:
            chk(f"Stats endpoint — {e}", False)
    else:
        chk("Stats endpoint (skipped — no token)", False)

    # 5. Unauthenticated request correctly rejected (security regression)
    try:
        code, _ = req("/api/v1/agents/stats")
        chk("Unauthenticated request rejected", code in (401, 403))
    except urllib.error.HTTPError as e:
        chk("Unauthenticated request rejected", e.code in (401, 403))
    except Exception as e:
        chk(f"Unauthenticated check — {e}", False)

    # 6. Prometheus metrics endpoint live
    try:
        r = urllib.request.Request(BASE_URL + "/metrics")
        with urllib.request.urlopen(r, timeout=10) as resp:
            body_text = resp.read().decode()
            chk(
                "Prometheus /metrics reachable",
                resp.status == 200 and "agentatlas_http_requests_total" in body_text
            )
    except Exception as e:
        chk(f"Prometheus /metrics — {e}", False)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\nSmoke test: {passed}/{total} passed")
    return passed == total


def lambda_handler(event, context):
    print("CodeDeploy AfterAllowTestTraffic hook invoked")
    print(f"Testing green set at: {BASE_URL}")
    print(f"Deployment ID: {event.get('DeploymentId')}")
    print(f"Lifecycle event token: {event.get('LifecycleEventHookExecutionId')}")

    deployment_id       = event["DeploymentId"]
    hook_execution_id   = event["LifecycleEventHookExecutionId"]

    try:
        passed = run_smoke_tests()
        status = "Succeeded" if passed else "Failed"
    except Exception as e:
        print(f"Smoke test raised an exception: {e}")
        status = "Failed"

    print(f"\nReporting status to CodeDeploy: {status}")
    codedeploy.put_lifecycle_event_hook_execution_status(
        deploymentId=deployment_id,
        lifecycleEventHookExecutionId=hook_execution_id,
        status=status
    )

    return {"status": status}
