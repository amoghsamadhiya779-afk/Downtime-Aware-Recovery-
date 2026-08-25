# ==============================================================================
# Payment Recovery Control Plane - Multi-Stage Container Image
# ==============================================================================

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8000 \
    ENVIRONMENT=production

WORKDIR /app

# Install system dependencies (curl for container health checks)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user and group for security
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Copy dependency specifications first for optimal layer caching
COPY pyproject.toml /app/

# Install application dependencies
RUN pip install --upgrade pip && \
    pip install .

# Copy application source code and assets
COPY agent/ /app/agent/
COPY datagen/ /app/datagen/
COPY evalharness/ /app/evalharness/
COPY dashboard/ /app/dashboard/
COPY scripts/ /app/scripts/
COPY .env.example /app/.env.example

# Create persistent data and logs directories with correct permissions
RUN mkdir -p /app/data /app/logs && \
    chown -R appuser:appuser /app

# Switch to non-root execution
USER appuser

# Expose control plane HTTP port
EXPOSE 8000

# Native Container Health Check targeting /api/health
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/health || exit 1

# Clean container startup entrypoint
CMD ["python", "scripts/serve_dashboard.py", "--host", "0.0.0.0", "--port", "8000", "--db", "data/dev.db"]
