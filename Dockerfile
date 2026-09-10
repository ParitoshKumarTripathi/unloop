# syntax=docker/dockerfile:1
# LiveKit Cloud build entrypoint. Keep this at the repository root because the
# deployed agent needs both agent/ and fixtures/ in its build context.

ARG PYTHON_VERSION=3.12
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
WORKDIR /app

COPY agent/pyproject.toml agent/uv.lock ./
RUN mkdir -p src && uv sync --locked --no-dev
RUN uv run --module livekit.agents download-files

COPY agent/src/ /app/src/
COPY fixtures/ /app/fixtures/

FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim

ARG UID=10001
RUN adduser --disabled-password --gecos "" --home "/app" --shell "/sbin/nologin" --uid "${UID}" appuser

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app

COPY --from=build --chown=appuser:appuser /app /app

USER appuser
CMD ["uv", "run", "python", "-m", "unloop.agent", "start"]
