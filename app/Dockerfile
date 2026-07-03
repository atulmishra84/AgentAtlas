# AgentAtlas — Production Dockerfile
# Multi-stage build: dependencies compiled separately from runtime image,
# so the final image has no build toolchain, no pip cache, no source of
# secondary supply-chain risk beyond what's actually needed to run.

# ── Stage 1: dependency build ────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Pin build tools; don't trust "latest" for anything that touches the supply chain
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc=4:12.2.0-3 \
    libpq-dev=15.* \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Runtime-only system deps — libpq5, not libpq-dev (no compiler headers in prod image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5=15.* \
    curl=7.* \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r agentatlas --gid=10001 \
    && useradd -r -g agentatlas --uid=10001 --home-dir=/app --shell=/sbin/nologin agentatlas

WORKDIR /app

# Copy only the installed packages from the builder, not the build toolchain
COPY --from=builder /root/.local /home/agentatlas/.local
ENV PATH=/home/agentatlas/.local/bin:$PATH \
    PYTHONPATH=/home/agentatlas/.local/lib/python3.12/site-packages \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --chown=agentatlas:agentatlas main.py database.py repositories.py seed.py ./

# Drop privileges before anything else runs
USER agentatlas

EXPOSE 8000

# Liveness probe target — separate from readiness (see k8s probes).
# Healthcheck here is for local `docker run` / docker-compose convenience;
# Kubernetes uses its own probes defined in the Deployment, not this.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# No shell-form CMD — exec form avoids an unnecessary shell process as PID 1
# and ensures SIGTERM from Kubernetes reaches uvicorn directly for graceful shutdown
CMD ["python3", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "30", \
     "--no-server-header"]
