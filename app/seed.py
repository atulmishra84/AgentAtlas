"""
AgentAtlas — Seed data
Author: Engineer Agent

Same seed data as the original main.py module-level dicts, now expressed
as rows to insert via the repository layer at startup. This preserves
demo continuity (same 9 agents, same 7 connectors) while moving the
data into the database.
"""
import hashlib
from datetime import datetime, timezone

SEED_TENANT = {"tenant_id": "ten_demo", "name": "Demo Health System", "plan": "enterprise",
               "created_at": datetime.now(timezone.utc)}

SEED_USERS = [
    {"user_id": "usr_admin", "username": "admin",
     "password_hash": hashlib.sha256(b"Admin@123").hexdigest(), "role": "admin", "tenant_id": "ten_demo"},
    {"user_id": "usr_analyst", "username": "analyst",
     "password_hash": hashlib.sha256(b"Analyst@123").hexdigest(), "role": "read_only", "tenant_id": "ten_demo"},
]

SEED_AGENTS = [
    {"agent_id": "agt_001", "tenant_id": "ten_demo", "name": "Customer Support Bot", "agent_type": "conversational",
     "framework": "langchain", "cloud": "azure", "env": "production", "status": "running",
     "model_provider": "openai", "model_name": "gpt-4o", "is_shadow": False, "is_orphaned": False,
     "connector": "azure_ai_foundry", "owner": "cs-team@corp.com", "tools": 5,
     "business_unit": "Customer Success", "region": "eastus", "endpoint_device": None, "extra": {}},
    {"agent_id": "agt_002", "tenant_id": "ten_demo", "name": "Sales Forecast Agent", "agent_type": "agentic",
     "framework": "crewai", "cloud": "aws", "env": "production", "status": "running",
     "model_provider": "anthropic", "model_name": "claude-3-5-sonnet", "is_shadow": False, "is_orphaned": False,
     "connector": "aws_bedrock", "owner": "finance@corp.com", "tools": 3,
     "business_unit": "Finance", "region": "us-east-1", "endpoint_device": None, "extra": {}},
    {"agent_id": "agt_003", "tenant_id": "ten_demo", "name": "Code Review Assistant", "agent_type": "agentic",
     "framework": "semantic_kernel", "cloud": "azure", "env": "dev", "status": "running",
     "model_provider": "openai", "model_name": "gpt-4o", "is_shadow": False, "is_orphaned": False,
     "connector": "github", "owner": "dev-team@corp.com", "tools": 2,
     "business_unit": "Engineering", "region": "eastus", "endpoint_device": None, "extra": {}},
    {"agent_id": "agt_004", "tenant_id": "ten_demo", "name": "Local Llama Instance", "agent_type": "agentic",
     "framework": "ollama", "cloud": "local", "env": "dev", "status": "running",
     "model_provider": "meta", "model_name": "llama3.1:70b", "is_shadow": True, "is_orphaned": True,
     "connector": "ollama", "owner": None, "tools": 0,
     "business_unit": None, "region": "local", "endpoint_device": "LAPTOP-JD042", "extra": {}},
    {"agent_id": "agt_005", "tenant_id": "ten_demo", "name": "HR Policy Chatbot", "agent_type": "conversational",
     "framework": "langchain", "cloud": "gcp", "env": "production", "status": "running",
     "model_provider": "google", "model_name": "gemini-1.5-pro", "is_shadow": False, "is_orphaned": False,
     "connector": "google_vertex", "owner": "hr@corp.com", "tools": 4,
     "business_unit": "Human Resources", "region": "us-central1", "endpoint_device": None, "extra": {}},
    {"agent_id": "agt_006", "tenant_id": "ten_demo", "name": "Supply Chain Optimizer", "agent_type": "orchestrator",
     "framework": "autogen", "cloud": "azure", "env": "production", "status": "stopped",
     "model_provider": "openai", "model_name": "gpt-4o", "is_shadow": False, "is_orphaned": False,
     "connector": "azure_ai_foundry", "owner": "ops@corp.com", "tools": 8,
     "business_unit": "Operations", "region": "westus2", "endpoint_device": None, "extra": {}},
    {"agent_id": "agt_007", "tenant_id": "ten_demo", "name": "Marketing Content Agent", "agent_type": "agentic",
     "framework": "crewai", "cloud": "aws", "env": "uat", "status": "running",
     "model_provider": "anthropic", "model_name": "claude-3-5-sonnet", "is_shadow": True, "is_orphaned": False,
     "connector": "aws_bedrock", "owner": None, "tools": 6,
     "business_unit": None, "region": "us-west-2", "endpoint_device": None, "extra": {}},
    {"agent_id": "agt_008", "tenant_id": "ten_demo", "name": "Compliance Monitor", "agent_type": "classifier",
     "framework": "langchain", "cloud": "azure", "env": "production", "status": "running",
     "model_provider": "openai", "model_name": "gpt-4o", "is_shadow": False, "is_orphaned": False,
     "connector": "azure_ai_foundry", "owner": "legal@corp.com", "tools": 2,
     "business_unit": "Legal & Compliance", "region": "eastus", "endpoint_device": None, "extra": {}},
    {"agent_id": "agt_009", "tenant_id": "ten_demo", "name": "Shadow ML Worker", "agent_type": "agentic",
     "framework": "custom", "cloud": "local", "env": "unknown", "status": "running",
     "model_provider": "mistral", "model_name": "mistral-7b", "is_shadow": True, "is_orphaned": True,
     "connector": "crowdstrike_edr", "owner": None, "tools": 0,
     "business_unit": None, "region": "local", "endpoint_device": "WORKSTATION-MK789", "extra": {}},
]

SEED_CONNECTORS = [
    {"connector_id": "azure_ai_foundry", "tenant_id": "ten_demo", "display_name": "Azure AI Foundry",
     "connector_type": "ai_platform", "status": "healthy", "agents_found": 4,
     "schedule": "0 */6 * * *", "credentials": {}, "config": {}, "is_enabled": True, "last_run": None},
    {"connector_id": "aws_bedrock", "tenant_id": "ten_demo", "display_name": "AWS Bedrock",
     "connector_type": "ai_platform", "status": "healthy", "agents_found": 3,
     "schedule": "0 */6 * * *", "credentials": {}, "config": {}, "is_enabled": True, "last_run": None},
    {"connector_id": "google_vertex", "tenant_id": "ten_demo", "display_name": "Google Vertex AI",
     "connector_type": "ai_platform", "status": "healthy", "agents_found": 2,
     "schedule": "0 */6 * * *", "credentials": {}, "config": {}, "is_enabled": True, "last_run": None},
    {"connector_id": "github", "tenant_id": "ten_demo", "display_name": "GitHub",
     "connector_type": "developer_platform", "status": "healthy", "agents_found": 2,
     "schedule": "0 */4 * * *", "credentials": {}, "config": {}, "is_enabled": True, "last_run": None},
    {"connector_id": "kubernetes", "tenant_id": "ten_demo", "display_name": "Kubernetes",
     "connector_type": "cloud_platform", "status": "warning", "agents_found": 0,
     "schedule": "*/30 * * * *", "credentials": {}, "config": {}, "is_enabled": True, "last_run": None},
    {"connector_id": "crowdstrike_edr", "tenant_id": "ten_demo", "display_name": "CrowdStrike EDR",
     "connector_type": "endpoint", "status": "healthy", "agents_found": 1,
     "schedule": "*/15 * * * *", "credentials": {}, "config": {}, "is_enabled": True, "last_run": None},
    {"connector_id": "ollama", "tenant_id": "ten_demo", "display_name": "Ollama",
     "connector_type": "agent_framework", "status": "healthy", "agents_found": 1,
     "schedule": "*/10 * * * *", "credentials": {}, "config": {}, "is_enabled": True, "last_run": None},
]

SEED_RELATIONSHIPS = [
    {"tenant_id": "ten_demo", "source_agent_id": "agt_001", "target_agent_id": "agt_008",
     "rel_type": "CALLS", "label": "Routes compliance checks"},
    {"tenant_id": "ten_demo", "source_agent_id": "agt_001", "target_agent_id": "agt_005",
     "rel_type": "DELEGATES_TO", "label": "Escalates HR queries"},
    {"tenant_id": "ten_demo", "source_agent_id": "agt_002", "target_agent_id": "agt_009",
     "rel_type": "USES_TOOL", "label": "Reads data pipeline output"},
]


async def seed_database(session):
    """Idempotent-ish seed: only inserts if the tenant doesn't already exist,
    so re-running on an already-seeded DB (e.g. local dev restart) is a no-op
    rather than a duplicate-key crash."""
    from repositories import TenantRepository
    tenant_repo = TenantRepository(session)
    existing = await tenant_repo.get("ten_demo")
    if existing:
        return False  # already seeded

    from sqlalchemy import insert
    from database import tenants, users, agents, connectors, relationships

    await session.execute(insert(tenants).values(**SEED_TENANT))
    for u in SEED_USERS:
        await session.execute(insert(users).values(**u))
    for a in SEED_AGENTS:
        await session.execute(insert(agents).values(**a, discovered_at=datetime.now(timezone.utc)))
    for c in SEED_CONNECTORS:
        await session.execute(insert(connectors).values(**c))
    for r in SEED_RELATIONSHIPS:
        await session.execute(insert(relationships).values(**r))
    await session.commit()
    return True
