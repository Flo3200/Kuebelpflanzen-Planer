# Multi-stage build: frontend (Node) -> runtime (Python with uv)
FROM node:24-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY agent/ /app/agent/
COPY docs/ /app/docs/
COPY --from=frontend /src/frontend/dist /app/frontend/dist
ENV PATH="/app/backend/.venv/bin:$PATH" KP_FRONTEND_DIST=/app/frontend/dist KP_FILES_DIR=/data/files
EXPOSE 8000
CMD ["bash", "/app/backend/docker-entrypoint.sh"]
