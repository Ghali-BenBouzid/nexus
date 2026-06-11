# Backend image. uv provides Python 3.13 + fast, reproducible installs.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Install dependencies first for layer caching; --no-install-project means we run
# from source (main:app) rather than installing "nexus" as a package.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Put the venv on PATH so alembic/uvicorn resolve directly.
ENV PATH="/app/.venv/bin:$PATH"

# Apply migrations, then serve. Shell form so $PORT (set by the host) expands.
CMD alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
