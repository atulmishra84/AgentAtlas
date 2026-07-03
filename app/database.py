"""
AgentAtlas — Database layer
Author: Engineer Agent
Built to: Architect's spec in 01_architecture.md

Engine is environment-driven: DATABASE_URL=sqlite+aiosqlite:///./local.db for dev,
postgresql+asyncpg://... for production (the AWS Terraform already provisions
the RDS instance this points to — see rds.tf db_secret_arn output).
"""
import os
from datetime import datetime, timezone

from sqlalchemy import (
    Table, Column, MetaData, String, Boolean, Integer, Text, DateTime, JSON, ForeignKey
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./agentatlas.db")

# OPTIMIZER FIX (Reviewer Finding 5): Architect's design doc set a hard constraint —
# RDS db.t4g.micro's default max_connections (~85) divided across up to
# ecs_max_count=4 autoscaled tasks means each task's pool must stay small.
# pool_size=4 + max_overflow=2 per task * 4 tasks = 24 max connections under full
# autoscale, comfortably under the RDS ceiling with headroom for psql/migrations.
# SQLite ignores pool_size (single-file, no real pooling) so this is a no-op in dev.
_is_sqlite = DATABASE_URL.startswith("sqlite")
_pool_kwargs = {} if _is_sqlite else {"pool_size": 4, "max_overflow": 2, "pool_timeout": 10, "pool_pre_ping": True}

engine = create_async_engine(
    DATABASE_URL,
    echo=os.environ.get("SQL_ECHO", "false") == "true",
    **_pool_kwargs,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# ── Query latency instrumentation ──────────────────────────────────────────
# Wired at the SQLAlchemy engine level via before/after cursor-execute events
# rather than decorating each of the ~30 repository methods individually —
# this captures every query, including ones added later, with zero per-method
# maintenance burden. The DB_QUERY_LATENCY histogram is declared in main.py;
# imported here lazily to avoid a circular import (main.py imports database.py).
def _instrument_query_timing():
    import time
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.monotonic()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        # Import here, not at module top, specifically to avoid the circular
        # import (main.py -> database.py -> main.py) that a top-level import
        # of DB_QUERY_LATENCY would create.
        try:
            from main import DB_QUERY_LATENCY
            duration = time.monotonic() - context._query_start_time
            # Rough operation classification from the SQL verb — exact enough
            # for a "is this table's queries getting slow" dashboard panel,
            # not meant to be a full query-plan analyzer.
            op = statement.strip().split()[0].upper() if statement.strip() else "UNKNOWN"
            table = "unknown"
            for kw in ("FROM", "INTO", "UPDATE"):
                if kw in statement.upper():
                    parts = statement.upper().split(kw, 1)[1].strip().split()
                    if parts:
                        table = parts[0].strip('"').lower()
                    break
            DB_QUERY_LATENCY.labels(repository=table, operation=op).observe(duration)
        except ImportError:
            pass  # main module not yet loaded (e.g. during Alembic migrations) — fine to skip


_instrument_query_timing()

metadata = MetaData()

# ── Schema — mirrors Architect's SQL design, expressed as SQLAlchemy Core Tables ──

tenants = Table(
    "tenants", metadata,
    Column("tenant_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("plan", String, nullable=False, default="enterprise"),
    Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
)

users = Table(
    "users", metadata,
    Column("user_id", String, primary_key=True),
    Column("username", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
    Column("role", String, nullable=False),
    Column("tenant_id", String, ForeignKey("tenants.tenant_id"), nullable=False),
)

agents = Table(
    "agents", metadata,
    Column("agent_id", String, primary_key=True),
    Column("tenant_id", String, ForeignKey("tenants.tenant_id"), nullable=False, index=True),
    Column("name", String, nullable=False),
    Column("agent_type", String, default="unknown"),
    Column("framework", String),
    Column("cloud", String),
    Column("env", String),
    Column("status", String, default="unknown"),
    Column("model_provider", String),
    Column("model_name", String),
    Column("is_shadow", Boolean, default=False),
    Column("is_orphaned", Boolean, default=False),
    Column("connector", String),
    Column("owner", String),
    Column("tools", Integer, default=0),
    Column("business_unit", String),
    Column("region", String),
    Column("endpoint_device", String),
    Column("discovered_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    Column("extra", JSON, default=dict),  # forward-compat field bag, per Architect note
)

connectors = Table(
    "connectors", metadata,
    Column("connector_id", String, primary_key=True),
    Column("tenant_id", String, ForeignKey("tenants.tenant_id"), primary_key=True),
    Column("display_name", String, nullable=False),
    Column("connector_type", String, nullable=False),
    Column("status", String, default="unknown"),
    Column("agents_found", Integer, default=0),
    Column("schedule", String, default="0 */6 * * *"),
    Column("last_run", DateTime(timezone=True), nullable=True),
    Column("credentials", JSON, default=dict),
    Column("config", JSON, default=dict),
    Column("is_enabled", Boolean, default=True),
)

discovery_jobs = Table(
    "discovery_jobs", metadata,
    Column("job_id", String, primary_key=True),
    Column("tenant_id", String, ForeignKey("tenants.tenant_id"), nullable=False, index=True),
    Column("connector_id", String, nullable=False),
    Column("job_type", String, nullable=False),
    Column("status", String, default="queued"),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("agents_found", Integer, default=0),
    Column("agents_updated", Integer, default=0),
)

siem_targets = Table(
    "siem_targets", metadata,
    Column("target_id", String, primary_key=True),
    Column("tenant_id", String, ForeignKey("tenants.tenant_id"), nullable=False, index=True),
    Column("name", String, nullable=False),
    Column("siem_type", String, nullable=False),
    Column("delivery_method", String, nullable=False),
    Column("config", JSON, default=dict),
    Column("event_filter", JSON, default=dict),
    Column("status", String, default="active"),
    Column("is_enabled", Boolean, default=True),
    Column("delivered", Integer, default=0),
    Column("failed", Integer, default=0),
    Column("last_export", DateTime(timezone=True), nullable=True),
)

events = Table(
    "events", metadata,
    Column("event_id", String, primary_key=True),
    Column("tenant_id", String, nullable=True, index=True),
    Column("event_type", String, nullable=False),
    Column("severity", String, default="info"),
    Column("payload", JSON, default=dict),
    Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True),
)

audit_log = Table(
    "audit_log", metadata,
    Column("log_id", String, primary_key=True),
    Column("tenant_id", String, nullable=True, index=True),
    Column("action", String, nullable=False),
    Column("resource", String, nullable=False),
    Column("username", String, nullable=False),
    Column("details", JSON, default=dict),
    Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
)

change_history = Table(
    "change_history", metadata,
    Column("change_id", String, primary_key=True),
    Column("agent_id", String, nullable=False, index=True),
    Column("tenant_id", String, nullable=False),
    Column("change_type", String, nullable=False),
    Column("changed_fields", JSON, default=list),
    Column("summary", Text),
    Column("connector_id", String),
    Column("changed_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    Column("version", Integer, nullable=False),
)

relationships = Table(
    "relationships", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String, nullable=False, index=True),
    Column("source_agent_id", String, nullable=False),
    Column("target_agent_id", String, nullable=False),
    Column("rel_type", String, nullable=False),
    Column("label", String),
)


async def init_db():
    """Create all tables. In production this is superseded by Alembic migrations
    (see migrations/ — Architect mandated Alembic, not ad-hoc create_all, for any
    environment where schema evolution matters). create_all is safe here because
    it's idempotent (checkfirst=True is the SQLAlchemy default)."""
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
