# Build context: repository root (run with `docker build -f global-market-agent/Dockerfile .`)
FROM python:3.11-slim

# System dependencies (curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv (pinned version for reproducibility)
RUN pip install --no-cache-dir uv==0.7.12

# --- MCP Server (changes less frequently, better layer caching) ---
WORKDIR /app/mcp-server
COPY global-market-mcp/pyproject.toml global-market-mcp/uv.lock ./
RUN uv sync --no-dev --no-install-project
COPY global-market-mcp/src ./src
COPY global-market-mcp/mcp_server.py ./
RUN uv sync --no-dev

# --- Backend Agent ---
WORKDIR /app
COPY global-market-agent/pyproject.toml global-market-agent/uv.lock ./
RUN uv sync --no-dev --no-install-project
COPY global-market-agent/src ./src
COPY global-market-agent/config ./config
RUN uv sync --no-dev

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/knowledge_base /app/logs && \
    chown -R appuser:appuser /app
USER appuser

# Environment
ENV MCP_SERVER_DIR=/app/mcp-server
ENV MCP_SERVER_COMMAND=uv
ENV MCP_SERVER_SCRIPT=mcp_server.py
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
