"""
AgentAtlas — Unit/Integration Test Suite
This is what `pytest tests/` in the CI pipeline actually executes — distinct
from security_gate.py (which is an external black-box probe) and smoke_test.py
(which is a fast post-deploy sanity check). These three serve different
purposes and intentionally overlap a little rather than relying on just one.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")

import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app


@pytest.fixture
async def client():
    # ASGITransport does NOT trigger FastAPI's startup/shutdown events by
    # default — without explicitly running the lifespan context, the app's
    # @app.on_event("startup") handler (which creates tables and seeds data)
    # never fires, and every test fails with "no such table: agents". This
    # is exactly the kind of test-harness gap that makes a green CI run
    # meaningless if not caught — found by actually running this suite.
    import main as main_module
    main_module.RATE_MW_STORE.clear()  # the login rate limiter is real, correct,
    # module-level state — exactly what makes it effective in production also
    # means a 17-test suite that each calls /auth/login will trip its own
    # 10-req/min throttle unless reset between tests. Resetting here, not
    # disabling the limiter, keeps the test honest about what's actually deployed.
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.fixture
async def admin_token(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin@123"})
    return r.json()["access_token"]


@pytest.fixture
async def analyst_token(client):
    r = await client.post("/api/v1/auth/login", json={"username": "analyst", "password": "Analyst@123"})
    return r.json()["access_token"]


class TestAuth:
    async def test_login_success(self, client):
        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin@123"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    async def test_login_wrong_password(self, client):
        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    async def test_login_nonexistent_user(self, client):
        r = await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
        assert r.status_code == 401


class TestAgents:
    async def test_search_requires_auth(self, client):
        r = await client.post("/api/v1/agents/search", json={})
        assert r.status_code in (401, 403, 422)

    async def test_search_returns_seeded_agents(self, client, admin_token):
        r = await client.post("/api/v1/agents/search", json={"page": 1, "page_size": 20},
                               headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.json()["total"] == 9

    async def test_shadow_filter(self, client, admin_token):
        r = await client.post("/api/v1/agents/search", json={"shadow_only": True},
                               headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.json()["total"] == 3

    async def test_stats_endpoint(self, client, admin_token):
        r = await client.get("/api/v1/agents/stats", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["shadow"] == 3
        assert body["orphaned"] == 2

    async def test_update_persists(self, client, admin_token):
        r = await client.patch("/api/v1/agents/agt_002", json={"owner": "pytest@test.com"},
                                headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        r2 = await client.get("/api/v1/agents/agt_002", headers={"Authorization": f"Bearer {admin_token}"})
        assert r2.json()["owner"] == "pytest@test.com"

    async def test_readonly_cannot_update(self, client, analyst_token):
        r = await client.patch("/api/v1/agents/agt_001", json={"owner": "hacker@test.com"},
                                headers={"Authorization": f"Bearer {analyst_token}"})
        assert r.status_code == 403


class TestConnectors:
    async def test_list_connectors(self, client, admin_token):
        r = await client.get("/api/v1/connectors", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert len(r.json()["connectors"]) == 7

    async def test_create_and_delete_connector(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = await client.post("/api/v1/connectors",
                               json={"connector_id": "pytest_conn", "display_name": "Pytest",
                                     "connector_type": "test"}, headers=headers)
        assert r.status_code == 200
        r2 = await client.delete("/api/v1/connectors/pytest_conn", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["deleted"] is True


class TestHealthEndpoints:
    async def test_liveness(self, client):
        r = await client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "alive"

    async def test_readiness(self, client):
        r = await client.get("/readyz")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    async def test_metrics_exposed(self, client):
        r = await client.get("/metrics")
        assert r.status_code == 200
        assert "agentatlas_http_requests_total" in r.text


class TestSecurity:
    async def test_jwt_none_algorithm_rejected(self, client):
        import base64, json as json_lib
        h64 = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
        p64 = base64.urlsafe_b64encode(json_lib.dumps({
            "sub": "x", "username": "admin", "role": "admin", "tenant_id": "ten_demo",
            "exp": 9999999999, "iat": 1, "jti": "x"
        }).encode()).rstrip(b"=").decode()
        r = await client.get("/api/v1/agents/stats", headers={"Authorization": f"Bearer {h64}.{p64}."})
        assert r.status_code == 401

    async def test_sql_injection_contained(self, client, admin_token):
        r = await client.post("/api/v1/search", json={"q": "' OR 1=1--"},
                               headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.json()["total"] < 100

    async def test_security_headers_present(self, client):
        r = await client.get("/health")
        assert "x-content-type-options" in {k.lower() for k in r.headers}
        assert "x-frame-options" in {k.lower() for k in r.headers}
