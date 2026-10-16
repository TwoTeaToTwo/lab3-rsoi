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
COPY services/flight-service/src services/flight-service/src
RUN uv sync --frozen --package flight-service --no-dev --no-editable

FROM python:3.13.15-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN useradd --uid 10001 --create-home flight
COPY --from=builder /app/.venv /app/.venv
COPY services/flight-service/alembic.ini ./alembic.ini
COPY services/flight-service/migrations ./migrations
COPY services/flight-service/docker/start.py ./start.py
USER flight
EXPOSE 8060
CMD ["python", "start.py"]
