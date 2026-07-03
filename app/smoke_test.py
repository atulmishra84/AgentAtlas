"""
AgentAtlas — Post-Deploy Smoke Test
Runs after every deploy to staging or production. Deliberately fast (target:
under 15 seconds) and narrow — this is NOT the security gate (that's a
separate, slower, more thorough pass). This answers one question: "did the
thing that just got deployed actually come up and serve traffic correctly?"
A failure here triggers automatic rollback in the production pipeline.
"""
import argparse, json, sys, time, urllib.error, urllib.request


def req(base, method, path, body=None, token=None, timeout=10):
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"_exception": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--timeout-seconds", type=int, default=60,
                     help="Total time to retry before declaring the deploy failed")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    print(f"Smoke testing {base} ...")

    # Retry loop — a pod that just started might need a few seconds before
    # the load balancer's health check marks it Ready and starts routing.
    deadline = time.time() + args.timeout_seconds
    healthy = False
    while time.time() < deadline:
        code, body = req(base, "GET", "/readyz")
        if code == 200:
            healthy = True
            break
        print(f"  readiness not yet 200 (got {code}), retrying...")
        time.sleep(3)

    if not healthy:
        print(f"FAILED: /readyz never returned 200 within {args.timeout_seconds}s")
        sys.exit(1)
    print("  PASS: readiness check")

    checks = [("Readiness check (with retry)", True)]  # already confirmed True above by the retry loop

    code, body = req(base, "GET", "/healthz")
    checks.append(("Liveness check", code == 200))

    code, body = req(base, "POST", "/api/v1/auth/login",
                      {"username": "admin", "password": "Admin@123"})
    token = body.get("access_token", "") if code == 200 else ""
    checks.append(("Login succeeds", bool(token)))

    if token:
        code, body = req(base, "GET", "/api/v1/agents/stats", token=token)
        checks.append(("Stats endpoint returns data", code == 200 and "total" in body))

        code, body = req(base, "GET", "/api/v1/connectors", token=token)
        checks.append(("Connectors endpoint returns data", code == 200 and len(body.get("connectors", [])) > 0))

    code, _ = req(base, "GET", "/api/v1/agents/stats")
    checks.append(("Unauthenticated request correctly rejected", code in (401, 403)))

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")

    print(f"\nSmoke test: {passed}/{total} passed")
    if passed < total:
        print("FAILED — deploy did not pass smoke test")
        sys.exit(1)
    print("PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
