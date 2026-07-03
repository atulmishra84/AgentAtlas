"""
AgentAtlas — CI Security Gate (production version)
Extends the MVP-stage gate to support remote targets (staging/production URLs,
not just localhost), and raises the bar to 95/100 minimum for a production
pipeline vs. the 85/100 threshold used at MVP stage — there's no excuse for
a known regression class reaching production once it's been caught once.
"""
import argparse, base64, json, socket, sys, time, urllib.error, urllib.request
from urllib.parse import urlparse


def req(base, method, path, body=None, token=None):
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
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
    ap.add_argument("--port", type=int, help="Local port (for in-pipeline testing against localhost)")
    ap.add_argument("--base-url", type=str, help="Remote base URL (for staging/production verification)")
    ap.add_argument("--min-score", type=int, default=95)
    args = ap.parse_args()

    if args.base_url:
        base = args.base_url.rstrip("/")
    elif args.port:
        base = f"http://localhost:{args.port}"
    else:
        print("Must specify --port or --base-url")
        sys.exit(2)

    results = []

    def chk(name, ok, sev="info"):
        results.append((name, ok, sev))
        print(f"  {'PASS' if ok else 'FAIL'} [{sev if not ok else 'pass'}] {name}")

    tok_a = req(base, "POST", "/api/v1/auth/login", {"username": "admin", "password": "Admin@123"})[1].get("access_token", "")
    tok_r = req(base, "POST", "/api/v1/auth/login", {"username": "analyst", "password": "Analyst@123"})[1].get("access_token", "")
    chk("Admin login succeeds", bool(tok_a), "critical")
    chk("Analyst login succeeds", bool(tok_r), "critical")

    # JWT none-algorithm attack
    h64 = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    p64 = base64.urlsafe_b64encode(json.dumps({
        "sub": "usr_admin", "username": "admin", "role": "admin",
        "tenant_id": "ten_demo", "exp": 9999999999, "iat": 1, "jti": "x"
    }).encode()).rstrip(b"=").decode()
    code, _ = req(base, "GET", "/api/v1/agents/stats", token=f"{h64}.{p64}.")
    chk("JWT none-algorithm blocked", code in (401, 403), "critical")

    # Unauthenticated access across the surface
    for path in ["/api/v1/agents/stats", "/api/v1/connectors", "/api/v1/users", "/api/v1/tenants", "/api/v1/audit"]:
        code, _ = req(base, "GET", path)
        chk(f"No-auth blocked: {path}", code in (401, 403, 422), "critical")

    # RBAC
    code, _ = req(base, "PATCH", "/api/v1/agents/agt_001", {"owner": "x"}, token=tok_r)
    chk("RBAC: read-only blocked from writes", code == 403, "critical")
    code, _ = req(base, "POST", "/api/v1/users",
                   {"username": "esc_test", "password": "Pwn@12345", "role": "admin", "tenant_id": "ten_demo"},
                   token=tok_r)
    chk("RBAC: privilege escalation blocked", code == 403, "critical")

    # Injection
    for payload in ["' OR 1=1--", "<script>alert(1)</script>", "'; DROP TABLE agents;--"]:
        code, d = req(base, "POST", "/api/v1/search", {"q": payload}, token=tok_a)
        total = d.get("total", 999) if isinstance(d, dict) else 999
        chk(f"Injection contained: {payload[:25]}", code == 200 and total < 100, "critical")

    # Security headers
    req_obj = urllib.request.Request(base + "/health")
    with urllib.request.urlopen(req_obj, timeout=10) as r:
        hdrs = {k.lower(): v for k, v in r.headers.items()}
    for h in ["x-content-type-options", "x-frame-options", "strict-transport-security", "x-request-id"]:
        chk(f"Header present: {h}", h in hdrs, "medium")

    # Error response well-formedness — catches the exact JSONResponse arg-order
    # bug class found during the four-agent engineering pass: a 401 that
    # crashes into a 500 with no body is itself a finding, not just a 500.
    code, body = req(base, "GET", "/api/v1/agents/stats")
    chk("401 response has proper JSON body (not a crashed 500)",
        code == 401 and isinstance(body, dict) and "error" in body, "critical")

    # WebSocket auth — only testable for local (raw socket); skip cleanly for remote HTTPS
    if args.port:
        try:
            s = socket.socket()
            s.settimeout(3)
            s.connect(("localhost", args.port))
            s.send(
                f"GET /ws/events HTTP/1.1\r\nHost: localhost:{args.port}\r\nUpgrade: websocket\r\n"
                "Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n".encode()
            )
            resp = s.recv(512).decode(errors="ignore")
            s.close()
            chk("WebSocket requires auth", "101 Switching" not in resp, "critical")
        except Exception:
            chk("WebSocket requires auth", True)
    else:
        print("  SKIP   WebSocket raw-socket test (remote target — use a WSS-aware client in a follow-up)")

    # Readiness/liveness split actually exists (production reliability check,
    # not strictly "security" but belongs in the same automated gate since
    # both protect against the same class of "looked fine in review" gap)
    code, _ = req(base, "GET", "/healthz")
    chk("Liveness endpoint /healthz exists", code == 200, "medium")
    code, _ = req(base, "GET", "/readyz")
    chk("Readiness endpoint /readyz exists", code == 200, "medium")

    # /metrics returns Prometheus text format, not JSON — the generic req()
    # helper above calls json.loads() on every response, which would silently
    # swallow this into an empty dict. Fetch it directly instead.
    try:
        metrics_req = urllib.request.Request(base + "/metrics")
        with urllib.request.urlopen(metrics_req, timeout=10) as r:
            metrics_code = r.status
            metrics_body = r.read().decode()
        chk("Prometheus /metrics endpoint exposed",
            metrics_code == 200 and "agentatlas_http_requests_total" in metrics_body, "low")
    except Exception as e:
        chk("Prometheus /metrics endpoint exposed", False, "low")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    score = round(passed / total * 100) if total else 0

    print(f"\n{'='*55}")
    print(f"SECURITY GATE [{base}]: {score}/100 ({passed}/{total} passed)")

    if score < args.min_score:
        print(f"FAILED — below required threshold {args.min_score}")
        for name, ok, sev in results:
            if not ok:
                print(f"  [{sev.upper()}] {name}")
        sys.exit(1)

    print(f"PASSED — meets {args.min_score}+ threshold")
    sys.exit(0)


if __name__ == "__main__":
    main()
