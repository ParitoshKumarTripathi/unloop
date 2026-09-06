# syntax=docker/dockerfile:1
#
# UNLOOP agent image, for LiveKit Cloud agent deployment.
#
# Adapted from livekit-examples/agent-starter-python. Two deliberate differences:
#
#  * Python is pinned to 3.12 rather than the starter's 3.14. livekit-agents 1.8.0
#    declares >=3.10,<3.15, so 3.14 is in range, but 3.12 is what the project is
#    developed and tested against and what uv.lock was resolved for. Matching them
#    removes a class of "works locally, not in the container" surprise.
#  * The build copies fixtures/ from the repo root. The agent's mock backend reads
#    its scenarios from there, so the image is not self-contained without it.
#
# Build from the REPOSITORY ROOT so both paths resolve:
#   docker build -f agent/Dockerfile -t unloop-agent .

ARG PYTHON_VERSION=3.12
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base

ENV PYTHONUNBUFFERED=1
# Compile to bytecode at build time so the first import does not pay for it. Agent
# cold start is on the critical path for a caller waiting in silence.
ENV UV_COMPILE_BYTECODE=1
ENV HF_HOME=/app/.cache/huggingface
ENV TORCH_HOME=/app/.cache/torch

# --- build stage -----------------------------------------------------------
FROM base AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      g++ \
      python3-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a code-only change does not re-resolve the world.
COPY agent/pyproject.toml agent/uv.lock ./
RUN mkdir -p src && uv sync --locked --no-dev

# Pre-download plugin model files (turn detector weights, VAD) before the source
# copy, so this expensive layer survives code changes.
RUN uv run --module livekit.agents download-files

COPY agent/ /app/
# The mock support backend reads its scenarios from the repo-root fixtures/ dir.
COPY fixtures/ /app/fixtures/

# --- runtime stage ---------------------------------------------------------
# Compilers are not carried into the final image.
FROM base

ARG UID=10001
RUN adduser \
      --disabled-password \
      --gecos "" \
      --home "/app" \
      --shell "/sbin/nologin" \
      --uid "${UID}" \
      appuser

COPY --from=build --chown=appuser:appuser /app /app

WORKDIR /app
USER appuser

# No secrets are baked in. RIME_API_KEY, LIVEKIT_* and any model-provider key are
# supplied at run time through LiveKit Cloud secret management.
CMD ["uv", "run", "src/unloop/agent.py", "start"]
