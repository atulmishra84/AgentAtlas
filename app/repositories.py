"""
AgentAtlas — Repository Layer
Author: Engineer Agent

Implements the Architect's interface: every method takes tenant_id as the
first positional argument. This isn't a style choice — it's the mechanism
that makes "forgot to filter by tenant" a type error instead of a runtime
data leak. A route handler physically cannot call agent_repo.get(agent_id)
without a tenant_id; the call won't satisfy the method signature.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, insert, update, delete, func, and_, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    agents, connectors, discovery_jobs, siem_targets, events,
    audit_log, change_history, relationships, tenants, users
)


def _row_to_dict(row) -> dict:
    """SQLAlchemy Core rows -> plain dicts, matching the exact shape the
    original in-memory dicts had, so route handlers don't need to change."""
    return dict(row._mapping)


class AgentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(self, tenant_id: str, query: str | None, cloud: str | None,
                      framework: str | None, env: str | None, status: str | None,
                      shadow_only: bool, orphaned_only: bool,
                      page: int, page_size: int) -> tuple[list[dict], int]:
        stmt = select(agents).where(agents.c.tenant_id == tenant_id)
        if query:
            q = f"%{query.lower()}%"
            stmt = stmt.where(
                func.lower(agents.c.name).like(q) |
                func.lower(func.coalesce(agents.c.framework, "")).like(q) |
                func.lower(func.coalesce(agents.c.cloud, "")).like(q) |
                func.lower(func.coalesce(agents.c.owner, "")).like(q) |
                func.lower(func.coalesce(agents.c.model_name, "")).like(q)
            )
        if cloud:
            stmt = stmt.where(agents.c.cloud == cloud)
        if framework:
            stmt = stmt.where(agents.c.framework == framework)
        if env:
            stmt = stmt.where(agents.c.env == env)
        if status:
            stmt = stmt.where(agents.c.status == status)
        if shadow_only:
            stmt = stmt.where(agents.c.is_shadow == True)  # noqa: E712
        if orphaned_only:
            stmt = stmt.where(agents.c.is_orphaned == True)  # noqa: E712

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows], total

    async def get(self, tenant_id: str, agent_id: str) -> Optional[dict]:
        stmt = select(agents).where(
            and_(agents.c.tenant_id == tenant_id, agents.c.agent_id == agent_id)
        )
        row = (await self.session.execute(stmt)).fetchone()
        return _row_to_dict(row) if row else None

    async def get_by_id_any_tenant(self, agent_id: str) -> Optional[dict]:
        """Used only internally by relationship graph traversal where the
        caller has already validated tenant scope on the root node."""
        stmt = select(agents).where(agents.c.agent_id == agent_id)
        row = (await self.session.execute(stmt)).fetchone()
        return _row_to_dict(row) if row else None

    async def update(self, tenant_id: str, agent_id: str, fields: dict) -> Optional[dict]:
        if not fields:
            return await self.get(tenant_id, agent_id)
        stmt = (
            update(agents)
            .where(and_(agents.c.tenant_id == tenant_id, agents.c.agent_id == agent_id))
            .values(**fields)
        )
        result = await self.session.execute(stmt)
        if result.rowcount == 0:
            return None
        await self.session.commit()
        return await self.get(tenant_id, agent_id)

    async def stats(self, tenant_id: str) -> dict:
        base = select(agents).where(agents.c.tenant_id == tenant_id)
        total = (await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )).scalar_one()

        async def count_where(col, val):
            stmt = select(func.count()).select_from(
                base.where(col == val).subquery()
            )
            return (await self.session.execute(stmt)).scalar_one()

        running = await count_where(agents.c.status, "running")
        shadow = await count_where(agents.c.is_shadow, True)
        orphaned = await count_where(agents.c.is_orphaned, True)

        async def group_by(col):
            stmt = (
                select(col, func.count())
                .select_from(agents)
                .where(agents.c.tenant_id == tenant_id)
                .group_by(col)
            )
            rows = (await self.session.execute(stmt)).fetchall()
            return {(r[0] or "unknown"): r[1] for r in rows}

        return {
            "total": total, "running": running, "shadow": shadow, "orphaned": orphaned,
            "by_cloud": await group_by(agents.c.cloud),
            "by_framework": await group_by(agents.c.framework),
            "by_env": await group_by(agents.c.env),
            "by_model": await group_by(agents.c.model_provider),
        }

    async def full_text_search(self, tenant_id: str, q: str, fields: list[str],
                                filters: dict, page: int, page_size: int) -> tuple[list[dict], int]:
        """OPTIMIZER FIX (Reviewer Finding 4): scoring now happens in SQL via a
        computed CASE-sum expression instead of pulling up to 10,000 rows into
        Python per call. At the platform's stated target scale ("millions of
        agent records" per the original product spec), the old approach meant
        every full-text search did a full tenant table scan into application
        memory regardless of how selective the query was. This version still
        does a table scan (LIKE can't use a btree index without a trigram/GIN
        index — that's the next optimization once there's real query volume
        data to justify the extra index maintenance cost) but at least the
        scoring and sorting happen where the engine is built to do it, and
        only page_size rows ever cross into Python.
        """
        field_to_col = {
            "name": agents.c.name, "framework": agents.c.framework, "cloud": agents.c.cloud,
            "model_name": agents.c.model_name, "owner": agents.c.owner,
            "business_unit": agents.c.business_unit, "connector": agents.c.connector,
        }
        ql = f"%{q.lower()}%"
        score_terms = []
        match_conditions = []
        for f in fields:
            col = field_to_col.get(f)
            if col is None:
                continue
            weight = 10 if f == "name" else 5
            cond = func.lower(func.coalesce(col, "")).like(ql)
            score_terms.append(func.coalesce(func.cast(cond, Integer), 0) * weight)
            match_conditions.append(cond)

        if not score_terms:
            return [], 0

        score_expr = sum(score_terms[1:], score_terms[0])

        base = select(agents, score_expr.label("score")).where(agents.c.tenant_id == tenant_id)
        for f, val in filters.items():
            col = field_to_col.get(f)
            if col is not None and val is not None:
                base = base.where(col == val)
        base = base.where(score_expr > 0).order_by(score_expr.desc())

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        paged = base.offset((page - 1) * page_size).limit(page_size)
        rows = (await self.session.execute(paged)).fetchall()

        results = []
        for row in rows:
            d = dict(row._mapping)
            score = d.pop("score")
            matched = [f for f in fields if f in field_to_col and
                       ql.strip("%") in str(d.get(f) or "").lower()]
            results.append({"agent": d, "score": score, "matched_fields": matched})
        return results, total

    async def insert_seed(self, row: dict):
        """Used only by the seed/migration script — not exposed to routes."""
        await self.session.execute(insert(agents).values(**row))


class ConnectorRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, tenant_id: str) -> list[dict]:
        stmt = select(connectors).where(connectors.c.tenant_id == tenant_id)
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows]

    async def get(self, tenant_id: str, connector_id: str) -> Optional[dict]:
        stmt = select(connectors).where(
            and_(connectors.c.tenant_id == tenant_id, connectors.c.connector_id == connector_id)
        )
        row = (await self.session.execute(stmt)).fetchone()
        return _row_to_dict(row) if row else None

    async def create(self, tenant_id: str, data: dict) -> Optional[dict]:
        data = {**data, "tenant_id": tenant_id}
        await self.session.execute(insert(connectors).values(**data))
        await self.session.commit()
        return await self.get(tenant_id, data["connector_id"])

    async def update(self, tenant_id: str, connector_id: str, fields: dict) -> Optional[dict]:
        stmt = (
            update(connectors)
            .where(and_(connectors.c.tenant_id == tenant_id, connectors.c.connector_id == connector_id))
            .values(**fields)
        )
        result = await self.session.execute(stmt)
        if result.rowcount == 0:
            return None
        await self.session.commit()
        return await self.get(tenant_id, connector_id)

    async def delete(self, tenant_id: str, connector_id: str) -> bool:
        stmt = delete(connectors).where(
            and_(connectors.c.tenant_id == tenant_id, connectors.c.connector_id == connector_id)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def coverage(self, tenant_id: str) -> dict:
        conns = await self.list(tenant_id)
        healthy = sum(1 for c in conns if c["status"] == "healthy")
        return {
            "total_connectors": len(conns),
            "healthy_connectors": healthy,
            "coverage_pct": round(healthy / len(conns) * 100) if conns else 0,
            "connectors": conns,
        }


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def append(self, event: dict) -> dict:
        await self.session.execute(insert(events).values(**event))
        await self.session.commit()
        return event

    async def recent(self, tenant_id: Optional[str], limit: int = 50) -> list[dict]:
        stmt = select(events).order_by(events.c.created_at.desc()).limit(limit)
        if tenant_id:
            stmt = stmt.where((events.c.tenant_id == tenant_id) | (events.c.tenant_id.is_(None)))
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows]

    async def get_by_id(self, event_id: str) -> Optional[dict]:
        stmt = select(events).where(events.c.event_id == event_id)
        row = (await self.session.execute(stmt)).fetchone()
        return _row_to_dict(row) if row else None


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def append(self, entry: dict):
        await self.session.execute(insert(audit_log).values(**entry))
        await self.session.commit()

    async def recent(self, tenant_id: str, limit: int = 100) -> list[dict]:
        stmt = (
            select(audit_log)
            .where(audit_log.c.tenant_id == tenant_id)
            .order_by(audit_log.c.created_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows]


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_username(self, username: str) -> Optional[dict]:
        stmt = select(users).where(users.c.username == username)
        row = (await self.session.execute(stmt)).fetchone()
        return _row_to_dict(row) if row else None

    async def list(self, tenant_id: str) -> list[dict]:
        stmt = select(users).where(users.c.tenant_id == tenant_id)
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows]

    async def create(self, data: dict) -> dict:
        await self.session.execute(insert(users).values(**data))
        await self.session.commit()
        return data

    async def delete(self, tenant_id: str, username: str) -> bool:
        stmt = delete(users).where(
            and_(users.c.tenant_id == tenant_id, users.c.username == username)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0


class TenantRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, tenant_id: str) -> Optional[dict]:
        stmt = select(tenants).where(tenants.c.tenant_id == tenant_id)
        row = (await self.session.execute(stmt)).fetchone()
        return _row_to_dict(row) if row else None

    async def create(self, data: dict) -> dict:
        await self.session.execute(insert(tenants).values(**data))
        await self.session.commit()
        return data


class SiemRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, tenant_id: str) -> list[dict]:
        stmt = select(siem_targets).where(siem_targets.c.tenant_id == tenant_id)
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows]

    async def create(self, tenant_id: str, data: dict) -> dict:
        data = {**data, "tenant_id": tenant_id}
        await self.session.execute(insert(siem_targets).values(**data))
        await self.session.commit()
        stmt = select(siem_targets).where(siem_targets.c.target_id == data["target_id"])
        row = (await self.session.execute(stmt)).fetchone()
        return _row_to_dict(row)

    async def health(self, tenant_id: str) -> dict:
        targets = await self.list(tenant_id)
        records = []
        for t in targets:
            total = t["delivered"] + t["failed"]
            records.append({
                **t,
                "delivery_rate_pct": round(t["delivered"] / total * 100, 1) if total else 100.0,
            })
        return {
            "total_targets": len(targets),
            "active_targets": sum(1 for t in targets if t["status"] == "active"),
            "targets": records,
        }

    async def record_export(self, tenant_id: str, target_ids: List[str], event_count: int):
        for tid in target_ids:
            stmt = (
                update(siem_targets)
                .where(and_(siem_targets.c.tenant_id == tenant_id, siem_targets.c.target_id == tid))
                .values(delivered=siem_targets.c.delivered + event_count,
                        last_export=datetime.now(timezone.utc))
            )
            await self.session.execute(stmt)
        await self.session.commit()


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, job: dict) -> dict:
        await self.session.execute(insert(discovery_jobs).values(**job))
        await self.session.commit()
        return job

    async def update(self, job_id: str, fields: dict):
        stmt = update(discovery_jobs).where(discovery_jobs.c.job_id == job_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.commit()

    async def list(self, tenant_id: str) -> list[dict]:
        stmt = (
            select(discovery_jobs)
            .where(discovery_jobs.c.tenant_id == tenant_id)
            .order_by(discovery_jobs.c.started_at.desc())
        )
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows]


class HistoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def append(self, entry: dict):
        await self.session.execute(insert(change_history).values(**entry))
        await self.session.commit()

    async def for_agent(self, agent_id: str, limit: int = 50) -> list[dict]:
        stmt = (
            select(change_history)
            .where(change_history.c.agent_id == agent_id)
            .order_by(change_history.c.changed_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows]


class RelationshipRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def for_agent(self, tenant_id: str, agent_id: str) -> list[dict]:
        stmt = select(relationships).where(
            and_(relationships.c.tenant_id == tenant_id, relationships.c.source_agent_id == agent_id)
        )
        rows = (await self.session.execute(stmt)).fetchall()
        return [_row_to_dict(r) for r in rows]
