FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
COPY apps/api/src ./src
RUN uv sync --frozen --no-dev

COPY apps/api/migrations ./migrations
COPY apps/api/alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src"
EXPOSE 8000
CMD ["uvicorn", "repomedic.transport.app:app", "--host", "0.0.0.0", "--port", "8000"]
