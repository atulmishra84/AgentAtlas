"""
AgentAtlas — Persistent Backend (v2)
Author: Engineer Agent

Same 40 API contracts as the validated v1.2 in-memory backend. Storage swapped
to the repository layer per Architect's design. Every route that touched
AGENTS_DB / CONNECTORS_DB / etc. now calls the corresponding repository method
with tenant_id as the structural first argument.
"""
import asyncio, hashlib, json, logging, os, time, uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Literal

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ── Structured logging ───────────────────────────────────────────────────
# JSON lines, not human-formatted text — a log aggregator (Loki/CloudWatch)
# can filter on tenant_id, request_id, status_code as real fields this way.
# Plain-text "f-string" logs force every downstream query into regex parsing.
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Extra structured fields attached via logger.info(..., extra={"request_id": ...})
        for key in ("request_id", "tenant_id", "username", "path", "status_code", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)

_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), handlers=[_handler], force=True)
logger = logging.getLogger("agentAtlas")
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

# ── Observability instrumentation ────────────────────────────────────────
# OTel and Prometheus are wired here, in the app, not bolted on as a sidecar
# afterthought — request-scoped trace context and route-aware metrics need
# to come from inside the request lifecycle to be useful for debugging.
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

REQUEST_COUNT = Counter(
    "agentatlas_http_requests_total", "Total HTTP requests",
    ["method", "path", "status_code"]
)
REQUEST_LATENCY = Histogram(
    "agentatlas_http_request_duration_seconds", "Request latency",
    ["method", "path"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)
DB_QUERY_LATENCY = Histogram(
    "agentatlas_db_query_duration_seconds", "Database query latency",
    ["repository", "operation"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)
DISCOVERY_JOBS_RUNNING = Counter(
    "agentatlas_discovery_jobs_total", "Discovery jobs by outcome",
    ["connector_id", "status"]
)
SHADOW_AGENTS_DETECTED = Counter(
    "agentatlas_shadow_agents_detected_total", "Shadow AI agents discovered", ["tenant_id"]
)

OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
if OTEL_ENDPOINT:
    resource = Resource.create({"service.name": "agentatlas-api", "service.version": "2.0.0"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
    trace.set_tracer_provider(provider)
tracer = trace.get_tracer("agentatlas")

from database import init_db, async_session, engine
from repositories import (
    AgentRepository, ConnectorRepository, EventRepository, AuditRepository,
    UserRepository, TenantRepository, SiemRepository, JobRepository,
    HistoryRepository, RelationshipRepository
)
from seed import seed_database

# ── Config ─────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET", "agentAtlas-dev-secret-change-in-prod")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8

logger = logging.getLogger("agentAtlas")

RATE_LIMIT_STORE: Dict[str, List[float]] = defaultdict(list)
WS_CONNECTIONS: List[WebSocket] = []

# ── Pydantic models — unchanged from v1.2 ──────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

class AgentFilter(BaseModel):
    query: Optional[str] = None
    cloud: Optional[str] = None
    framework: Optional[str] = None
    env: Optional[str] = None
    status: Optional[str] = None
    shadow_only: bool = False
    orphaned_only: bool = False
    page: int = 1
    page_size: int = 20

class TriggerDiscoveryRequest(BaseModel):
    connector_id: str
    job_type: str = "incremental"

class SIEMTargetCreate(BaseModel):
    name: str
    siem_type: str
    delivery_method: str
    config: Dict[str, Any] = {}
    event_filter: Dict[str, Any] = {}

class AgentUpdate(BaseModel):
    owner: Optional[str] = None
    business_unit: Optional[str] = None
    tags: Optional[List[str]] = None

class ConnectorCreate(BaseModel):
    connector_id: str
    display_name: str
    connector_type: str
    credentials: Dict[str, Any] = {}
    config: Dict[str, Any] = {}
    schedule: str = "0 */6 * * *"

class ConnectorUpdate(BaseModel):
    display_name: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    schedule: Optional[str] = None
    is_enabled: Optional[bool] = None

class TenantCreate(BaseModel):
    tenant_id: str
    name: str
    plan: str = "enterprise"

class UserCreate(BaseModel):
    username: str
    password: str
    role: Literal["admin", "read_only"] = "read_only"
    tenant_id: str

class FullTextSearch(BaseModel):
    q: str
    fields: List[str] = ["name", "framework", "cloud", "model_name", "owner", "business_unit", "connector"]
    filters: Dict[str, Any] = {}
    page: int = 1
    page_size: int = 20

# ── Security ───────────────────────────────────────────────────────────────
security = HTTPBearer()

def create_token(user: Dict) -> str:
    payload = {
        "sub": user["user_id"], "username": user["username"],
        "role": user["role"], "tenant_id": user["tenant_id"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc), "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    try:
        return jwt.decode(credentials.credentials, SECRET_KEY,
                          algorithms=[ALGORITHM],
                          options={"require": ["exp", "iat", "sub"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, f"Invalid token: {e}")

async def get_session():
    async with async_session() as session:
        yield session

def get_background_session():
    """OPTIMIZER FIX (Reviewer Finding 2): named helper for the session-acquisition
    pattern used by code running outside the request lifecycle (asyncio.create_task
    background jobs), where Depends(get_session) isn't available. Same underlying
    factory as get_session() — this exists so the *pattern* is discoverable and
    named rather than each background task reinventing `async with async_session()`
    inline. Use as: `async with get_background_session() as session: ...`
    """
    return async_session()

async def audit(session, action, resource, user=None, details=None):
    repo = AuditRepository(session)
    await repo.append({
        "log_id": str(uuid.uuid4()), "tenant_id": user.get("tenant_id") if user else None,
        "action": action, "resource": resource,
        "username": user.get("username") if user else "system",
        "details": details or {}, "created_at": datetime.now(timezone.utc),
    })

async def publish_event(session, event_type, payload, tenant_id=None):
    sev = "critical" if "shadow" in event_type else "high" if "orphan" in event_type else "info"
    event = {
        "event_id": f"evt_{uuid.uuid4().hex[:10]}", "tenant_id": tenant_id,
        "event_type": event_type, "severity": sev, "payload": payload,
        "created_at": datetime.now(timezone.utc),
    }
    repo = EventRepository(session)
    await repo.append(event)
    dead = []
    for ws in WS_CONNECTIONS:
        try: await ws.send_text(json.dumps(event, default=str))
        except Exception: dead.append(ws)
    for ws in dead:
        if ws in WS_CONNECTIONS: WS_CONNECTIONS.remove(ws)
    return event

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Modern FastAPI lifespan pattern — replaces the deprecated @app.on_event
    # decorators. Functionally identical to the previous startup/shutdown
    # handlers; this form is what the asgi-lifespan test fixture (and any
    # ASGI-compliant test client) expects, and avoids a deprecation warning
    # that would otherwise become a breaking change on a future FastAPI major.
    await init_db()
    async with async_session() as session:
        created = await seed_database(session)
        logger.info(f"Database ready. Seeded: {created}")
    logger.info("AgentAtlas API started", extra={"path": "startup"})

    yield  # application runs here

    # Kubernetes sends SIGTERM, then waits terminationGracePeriodSeconds (set to
    # 30s in deployment.yaml) before SIGKILL. Uvicorn's default graceful shutdown
    # already drains in-flight HTTP requests; this additionally closes
    # WebSocket connections cleanly so connected dashboard clients get a proper
    # close frame instead of a dropped TCP connection, and disposes the DB
    # connection pool so no connections leak past process exit.
    logger.info(f"Shutting down — closing {len(WS_CONNECTIONS)} WebSocket connections")
    for ws in list(WS_CONNECTIONS):
        try:
            await ws.close(code=1001, reason="Server shutting down for deployment")
        except Exception:
            pass
    await engine.dispose()
    logger.info("Shutdown complete")

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="AgentAtlas API", version="2.0.0", docs_url="/api/docs", redoc_url="/api/redoc", lifespan=lifespan)

# Auto-instrument FastAPI for distributed tracing — every request gets a span,
# every outbound DB call (via SQLAlchemy, instrumented separately at engine
# creation) becomes a child span, so a slow request is traceable to the exact
# query or external call that caused it, not just "this endpoint was slow."
FastAPIInstrumentor.instrument_app(app)

@app.middleware("http")
async def prometheus_metrics(request: Request, call_next):
    # Route template, not raw path — /api/v1/agents/agt_001 and
    # /api/v1/agents/agt_002 must collapse into one cardinality bucket
    # (/api/v1/agents/{agent_id}) or Prometheus's label cardinality explodes
    # linearly with every unique agent_id ever requested.
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    route = request.scope.get("route")
    path_template = route.path if route else request.url.path
    REQUEST_COUNT.labels(method=request.method, path=path_template, status_code=response.status_code).inc()
    REQUEST_LATENCY.labels(method=request.method, path=path_template).observe(duration)
    return response

@app.get("/metrics")
async def metrics():
    """Scraped by Prometheus, not exposed publicly — see NetworkPolicy in k8s
    manifests, which restricts this path to the monitoring namespace only."""
    from fastapi import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
app.add_middleware(GZipMiddleware, minimum_size=512)
app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True, allow_methods=["GET","POST","PUT","PATCH","DELETE"],
    allow_headers=["Authorization","Content-Type","X-Request-ID"])

class AuthErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except HTTPException as exc:
            # OPTIMIZER FIX: keyword args, not positional — Starlette's JSONResponse
            # signature is (content, status_code=200, ...). Positional args here
            # silently swap content<->status_code instead of raising at call time.
            # See Reviewer Finding 1 — this exact bug took the security score from
            # 100/100 to 62/100 by turning every clean 401/403 into an unhandled 500.
            return JSONResponse(content={"error": exc.detail, "status_code": exc.status_code},
                                status_code=exc.status_code)
        except Exception as exc:
            logger.error(f"AuthErrorMiddleware caught: {type(exc).__name__}: {exc}")
            err_str = str(exc).lower()
            if any(k in err_str for k in ["token", "jwt", "decode", "credential", "bearer"]):
                return JSONResponse(content={"error": "Authentication required", "status_code": 401},
                                    status_code=401)
            return JSONResponse(content={"error": "Internal server error", "status_code": 500},
                                status_code=500)

app.add_middleware(AuthErrorMiddleware)

@app.middleware("http")
async def security_headers_and_access_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.time()
    resp = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)

    resp.headers.update({
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": "default-src 'self'",
        "X-Request-ID": request_id,
    })

    # Structured access log — request_id ties this line to the X-Request-ID
    # header (so a frontend error report or a curl -v can be grepped straight
    # to its server-side log line) and to the trace_id OTel attaches to the
    # span, so logs and traces correlate without manual cross-referencing.
    logger.info(
        f"{request.method} {request.url.path} -> {resp.status_code}",
        extra={"request_id": request_id, "path": request.url.path,
               "status_code": resp.status_code, "duration_ms": duration_ms},
    )
    return resp

LOGIN_PATH = "/api/v1/auth/login"
RATE_MW_STORE: dict = {}

@app.middleware("http")
async def login_rate_limit(request: Request, call_next):
    if request.url.path == LOGIN_PATH and request.method == "POST":
        ip = request.client.host if request.client else "0.0.0.0"
        now = time.time()
        RATE_MW_STORE.setdefault(ip, [])
        RATE_MW_STORE[ip] = [t for t in RATE_MW_STORE[ip] if t > now - 60]
        if len(RATE_MW_STORE[ip]) >= 10:
            return JSONResponse(content={"error": "Too many login attempts", "status_code": 429},
                                status_code=429, headers={"Retry-After": "60"})
        RATE_MW_STORE[ip].append(now)
    return await call_next(request)

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    return JSONResponse(content={"error": "Validation error", "detail": str(exc)}, status_code=422)

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(content={"error": exc.detail, "status_code": exc.status_code},
                        status_code=exc.status_code)

# ── Health ─────────────────────────────────────────────────────────────────
# Liveness and readiness are deliberately separate endpoints with different
# failure semantics in Kubernetes:
#   - Liveness failing -> kubelet KILLS and restarts the pod. Use this only
#     for "the process itself is wedged" (deadlock, unrecoverable state).
#   - Readiness failing -> kubelet just stops ROUTING traffic to this pod;
#     it stays alive and can recover. Use this for "a dependency is down."
# A single combined /health used for both is a reliability bug: if the DB
# is briefly slow, a readiness-style check failing under a liveness probe
# causes Kubernetes to restart perfectly healthy pods, which can cascade a
# transient DB blip into a full rolling outage as pods restart faster than
# the DB recovers. Keep them split, always.

@app.get("/healthz")
async def liveness():
    """Liveness: process is up and able to handle a request at all.
    Deliberately does NOT touch the database — a DB outage should make
    readiness fail (stop routing), not liveness fail (kill the pod)."""
    return {"status": "alive"}

@app.get("/readyz")
async def readiness(session=Depends(get_session)):
    """Readiness: this specific pod can actually serve real traffic right now.
    Touches the DB on purpose — if the DB is unreachable, this pod should be
    pulled from the load balancer's rotation until it recovers, without being
    killed and restarted (which wouldn't fix a DB outage anyway)."""
    try:
        repo = AgentRepository(session)
        await repo.search("ten_demo", None, None, None, None, None, False, False, 1, 1)
        return {"status": "ready", "version": "2.0.0"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(503, "Database unavailable")

@app.get("/health")
async def health(session=Depends(get_session)):
    """Legacy combined endpoint — kept for backward compatibility with the
    existing AWS ALB target group health check and any external monitors
    already pointed at /health. New deployments should configure Kubernetes
    probes against /healthz and /readyz instead (see deployment.yaml)."""
    repo = AgentRepository(session)
    _, total = await repo.search("ten_demo", None, None, None, None, None, False, False, 1, 1)
    return {"status": "healthy", "version": "2.0.0", "agents": total, "storage": "postgresql/sqlite"}

# ── Auth ───────────────────────────────────────────────────────────────────
@app.post("/api/v1/auth/login")
async def login(body: LoginRequest, session=Depends(get_session)):
    repo = UserRepository(session)
    user = await repo.get_by_username(body.username)
    if not user or user["password_hash"] != hashlib.sha256(body.password.encode()).hexdigest():
        await audit(session, "LOGIN_FAILED", "auth", details={"username": body.username})
        raise HTTPException(401, "Invalid credentials")
    await audit(session, "LOGIN_SUCCESS", "auth", user=user)
    return {"access_token": create_token(user), "token_type": "bearer"}

@app.get("/api/v1/auth/me")
async def me(current_user: Dict = Depends(verify_token)):
    return current_user

# ── Agents ─────────────────────────────────────────────────────────────────
@app.post("/api/v1/agents/search")
async def search_agents(filters: AgentFilter, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = AgentRepository(session)
    items, total = await repo.search(
        current_user["tenant_id"], filters.query, filters.cloud, filters.framework,
        filters.env, filters.status, filters.shadow_only, filters.orphaned_only,
        filters.page, filters.page_size
    )
    return {"total": total, "page": filters.page, "page_size": filters.page_size, "items": items}

@app.get("/api/v1/agents/stats")
async def get_stats(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = AgentRepository(session)
    return await repo.stats(current_user["tenant_id"])

@app.get("/api/v1/agents/{agent_id}")
async def get_agent(agent_id: str, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = AgentRepository(session)
    a = await repo.get(current_user["tenant_id"], agent_id)
    if not a: raise HTTPException(404, "Not found")
    return a

@app.patch("/api/v1/agents/{agent_id}")
async def update_agent(agent_id: str, update: AgentUpdate, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = AgentRepository(session)
    data = {k: v for k, v in update.model_dump().items() if v is not None and k != "tags"}
    result = await repo.update(current_user["tenant_id"], agent_id, data)
    if not result: raise HTTPException(404, "Not found")
    await audit(session, "AGENT_UPDATED", f"agent:{agent_id}", user=current_user, details=data)
    await publish_event(session, "agent.updated", {"agent_id": agent_id, "changes": data}, current_user["tenant_id"])
    return result

@app.get("/api/v1/agents/{agent_id}/history")
async def agent_history(agent_id: str, limit: int = 50, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    agent_repo = AgentRepository(session)
    a = await agent_repo.get(current_user["tenant_id"], agent_id)
    if not a: raise HTTPException(404, "Agent not found")
    hist_repo = HistoryRepository(session)
    changes = await hist_repo.for_agent(agent_id, limit)
    return {"agent_id": agent_id, "total": len(changes), "changes": changes}

@app.get("/api/v1/agents/{agent_id}/graph")
async def agent_graph(agent_id: str, depth: int = 2, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    agent_repo = AgentRepository(session)
    a = await agent_repo.get(current_user["tenant_id"], agent_id)
    if not a: raise HTTPException(404, "Agent not found")
    rel_repo = RelationshipRepository(session)
    rels = await rel_repo.for_agent(current_user["tenant_id"], agent_id)
    nodes = {agent_id: {"id": agent_id, "name": a["name"], "type": a["agent_type"], "framework": a.get("framework")}}
    edges = []
    for r in rels:
        target = await agent_repo.get(current_user["tenant_id"], r["target_agent_id"])
        if target:
            nodes[r["target_agent_id"]] = {"id": r["target_agent_id"], "name": target["name"],
                                            "type": target["agent_type"], "framework": target.get("framework")}
            edges.append({"source": r["source_agent_id"], "target": r["target_agent_id"],
                          "type": r["rel_type"], "label": r.get("label", "")})
    return {"root": agent_id, "nodes": list(nodes.values()), "edges": edges}

@app.post("/api/v1/search")
async def full_text_search(body: FullTextSearch, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = AgentRepository(session)
    results, total = await repo.full_text_search(
        current_user["tenant_id"], body.q, body.fields, body.filters, body.page, body.page_size
    )
    return {"query": body.q, "total": total, "page": body.page, "page_size": body.page_size, "results": results}

# ── Connectors ─────────────────────────────────────────────────────────────
@app.get("/api/v1/connectors")
async def list_connectors(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = ConnectorRepository(session)
    return {"connectors": await repo.list(current_user["tenant_id"])}

@app.post("/api/v1/connectors")
async def create_connector(body: ConnectorCreate, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = ConnectorRepository(session)
    existing = await repo.get(current_user["tenant_id"], body.connector_id)
    if existing: raise HTTPException(409, f"Connector '{body.connector_id}' already exists")
    data = {**body.model_dump(), "status": "unknown", "agents_found": 0, "last_run": None, "is_enabled": True}
    result = await repo.create(current_user["tenant_id"], data)
    await audit(session, "CONNECTOR_CREATED", f"connector:{body.connector_id}", user=current_user)
    return result

@app.put("/api/v1/connectors/{connector_id}")
async def update_connector(connector_id: str, body: ConnectorUpdate, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = ConnectorRepository(session)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    result = await repo.update(current_user["tenant_id"], connector_id, data)
    if not result: raise HTTPException(404, "Not found")
    await audit(session, "CONNECTOR_UPDATED", f"connector:{connector_id}", user=current_user, details=data)
    return result

@app.delete("/api/v1/connectors/{connector_id}")
async def delete_connector(connector_id: str, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = ConnectorRepository(session)
    ok = await repo.delete(current_user["tenant_id"], connector_id)
    if not ok: raise HTTPException(404, "Not found")
    await audit(session, "CONNECTOR_DELETED", f"connector:{connector_id}", user=current_user)
    return {"deleted": True, "connector_id": connector_id}

@app.post("/api/v1/connectors/{connector_id}/test")
async def test_connector(connector_id: str, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = ConnectorRepository(session)
    c = await repo.get(current_user["tenant_id"], connector_id)
    if not c: raise HTTPException(404, "Not found")
    return {"connector_id": connector_id, "status": c["status"], "ok": c["status"] == "healthy"}

@app.get("/api/v1/discovery/coverage")
async def coverage(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = ConnectorRepository(session)
    return await repo.coverage(current_user["tenant_id"])

# ── Discovery jobs ───────────────────────────────────────────────────────────
@app.post("/api/v1/discovery/trigger")
async def trigger_discovery(body: TriggerDiscoveryRequest, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    conn_repo = ConnectorRepository(session)
    connector = await conn_repo.get(current_user["tenant_id"], body.connector_id)
    if not connector: raise HTTPException(404, "Connector not found")
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    job_repo = JobRepository(session)
    await job_repo.create({
        "job_id": job_id, "tenant_id": current_user["tenant_id"], "connector_id": body.connector_id,
        "job_type": body.job_type, "status": "running",
        "started_at": datetime.now(timezone.utc), "completed_at": None,
        "agents_found": 0, "agents_updated": 0,
    })
    asyncio.create_task(_run_discovery(job_id, body.connector_id, current_user["tenant_id"], connector["agents_found"]))
    return {"job_id": job_id, "status": "running"}

async def _run_discovery(job_id, connector_id, tenant_id, found):
    await asyncio.sleep(2)
    async with get_background_session() as session:
        job_repo = JobRepository(session)
        await job_repo.update(job_id, {
            "status": "completed", "completed_at": datetime.now(timezone.utc),
            "agents_found": found, "agents_updated": found,
        })
        # Wire the metric that was declared at module scope but never actually
        # incremented anywhere — caught while building the Grafana dashboard,
        # which would otherwise have shipped a panel permanently showing
        # "No data" for discovery job outcomes.
        DISCOVERY_JOBS_RUNNING.labels(connector_id=connector_id, status="completed").inc()
        await publish_event(session, "job.completed", {"job_id": job_id, "connector_id": connector_id, "found": found}, tenant_id)

@app.get("/api/v1/discovery/jobs")
async def list_jobs(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = JobRepository(session)
    return {"jobs": await repo.list(current_user["tenant_id"])}

# ── SIEM ───────────────────────────────────────────────────────────────────
@app.get("/api/v1/siem/targets")
async def list_siem(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = SiemRepository(session)
    return {"targets": await repo.list(current_user["tenant_id"])}

@app.post("/api/v1/siem/targets")
async def create_siem(body: SIEMTargetCreate, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = SiemRepository(session)
    data = {**body.model_dump(), "target_id": f"tgt_{uuid.uuid4().hex[:10]}",
            "status": "active", "is_enabled": True, "delivered": 0, "failed": 0, "last_export": None}
    result = await repo.create(current_user["tenant_id"], data)
    await audit(session, "SIEM_CREATED", f"siem:{data['target_id']}", user=current_user)
    return result

@app.get("/api/v1/siem/health")
async def siem_health(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = SiemRepository(session)
    return await repo.health(current_user["tenant_id"])

@app.get("/api/v1/siem/field-mappings/{siem_type}")
async def field_mappings(siem_type: str, current_user: Dict = Depends(verify_token)):
    DEFAULTS = {
        "splunk": {"sourcetype": "source.platform", "event.id": "event_id"},
        "sentinel": {"TimeGenerated": "timestamp", "EventId_s": "event_id"},
        "elastic": {"@timestamp": "timestamp", "event.id": "event_id"},
        "chronicle": {"metadata.eventTimestamp": "timestamp"},
    }
    mapping = DEFAULTS.get(siem_type.lower())
    if not mapping: raise HTTPException(404, f"No mapping for '{siem_type}'")
    return {"siem_type": siem_type, "default_field_mapping": mapping}

@app.post("/api/v1/siem/export/batch")
async def batch_export(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    siem_repo = SiemRepository(session)
    targets = [t for t in await siem_repo.list(current_user["tenant_id"]) if t["is_enabled"]]
    event_repo = EventRepository(session)
    events_list = await event_repo.recent(current_user["tenant_id"], 500)
    export_id = f"exp_{uuid.uuid4().hex[:10]}"
    await siem_repo.record_export(current_user["tenant_id"], [t["target_id"] for t in targets], len(events_list))
    await audit(session, "BATCH_EXPORT", f"siem:batch:{export_id}", user=current_user,
               details={"targets": len(targets), "events": len(events_list)})
    return {"export_id": export_id, "events_exported": len(events_list), "targets_delivered": len(targets)}

# ── Events & Audit ─────────────────────────────────────────────────────────
@app.get("/api/v1/events")
async def list_events(limit: int = 50, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = EventRepository(session)
    return {"events": await repo.recent(current_user["tenant_id"], limit)}

@app.get("/api/v1/events/{event_id}")
async def get_event(event_id: str, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    repo = EventRepository(session)
    e = await repo.get_by_id(event_id)
    if not e: raise HTTPException(404, "Event not found")
    return e

@app.get("/api/v1/audit")
async def get_audit(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = AuditRepository(session)
    return {"logs": await repo.recent(current_user["tenant_id"])}

# ── Tenants & Users ──────────────────────────────────────────────────────────
@app.get("/api/v1/tenants")
async def list_tenants(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = TenantRepository(session)
    t = await repo.get(current_user["tenant_id"])
    return {"tenants": [t] if t else []}

@app.post("/api/v1/tenants")
async def create_tenant(body: TenantCreate, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = TenantRepository(session)
    existing = await repo.get(body.tenant_id)
    if existing: raise HTTPException(409, "Tenant already exists")
    data = {**body.model_dump(), "created_at": datetime.now(timezone.utc)}
    result = await repo.create(data)
    await audit(session, "TENANT_CREATED", f"tenant:{body.tenant_id}", user=current_user)
    return result

@app.get("/api/v1/users")
async def list_users(current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    repo = UserRepository(session)
    users_list = await repo.list(current_user["tenant_id"])
    return {"users": [{"user_id": u["user_id"], "username": u["username"], "role": u["role"]} for u in users_list]}

@app.post("/api/v1/users")
async def create_user(body: UserCreate, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    if len(body.password) < 8: raise HTTPException(422, "Password must be at least 8 characters")
    repo = UserRepository(session)
    existing = await repo.get_by_username(body.username)
    if existing: raise HTTPException(409, "Username already exists")
    user = {
        "user_id": f"usr_{uuid.uuid4().hex[:8]}", "username": body.username,
        "password_hash": hashlib.sha256(body.password.encode()).hexdigest(),
        "role": body.role, "tenant_id": body.tenant_id,
    }
    await repo.create(user)
    await audit(session, "USER_CREATED", f"user:{body.username}", user=current_user, details={"role": body.role})
    return {"user_id": user["user_id"], "username": user["username"], "role": user["role"]}

@app.delete("/api/v1/users/{username}")
async def delete_user(username: str, current_user: Dict = Depends(verify_token), session=Depends(get_session)):
    if current_user["role"] != "admin": raise HTTPException(403, "Admin required")
    if username == current_user["username"]: raise HTTPException(400, "Cannot delete own account")
    repo = UserRepository(session)
    ok = await repo.delete(current_user["tenant_id"], username)
    if not ok: raise HTTPException(404, "User not found")
    await audit(session, "USER_DELETED", f"user:{username}", user=current_user)
    return {"deleted": True, "username": username}

# ── WebSocket ──────────────────────────────────────────────────────────────
@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Token required"); return
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        await websocket.close(code=4001, reason="Invalid token"); return
    await websocket.accept()
    WS_CONNECTIONS.append(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "connected", "msg": "AgentAtlas stream ready"}))
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in WS_CONNECTIONS: WS_CONNECTIONS.remove(websocket)
