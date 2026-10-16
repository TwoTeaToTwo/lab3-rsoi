FROM ghcr.io/astral-sh/uv:0.12.3 AS uv

FROM python:3.13.15-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY services/bonus-service/pyproject.toml services/bonus-service/pyproject.toml
COPY services/flight-service/pyproject.toml services/flight-service/pyproject.toml
COPY services/ticket-service/pyproject.toml services/ticket-service/pyproject.toml
COPY services/gateway/pyproject.toml services/gateway/pyproject.toml
COPY services/bonus-service/src services/bonus-service/src
RUN uv sync --frozen --package bonus-service --no-dev --no-editable

FROM python:3.13.15-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN useradd --uid 10001 --create-home bonus
COPY --from=builder /app/.venv /app/.venv
COPY services/bonus-service/alembic.ini ./alembic.ini
COPY services/bonus-service/migrations ./migrations
COPY services/bonus-service/docker/start.py ./start.py
USER bonus
EXPOSE 8050
CMD ["python", "start.py"]
