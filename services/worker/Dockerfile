# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /workspace

COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
COPY ml ./ml
COPY services ./services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group ml

FROM ${PYTHON_IMAGE} AS runtime

RUN groupadd --gid 10001 recoveryos \
    && useradd --uid 10001 --gid recoveryos --create-home --shell /usr/sbin/nologin recoveryos

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVICE_NAME=recoveryos-worker
WORKDIR /workspace/services/worker

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=recoveryos:recoveryos /workspace/packages /workspace/packages
COPY --from=builder --chown=recoveryos:recoveryos /workspace/ml /workspace/ml
COPY --from=builder --chown=recoveryos:recoveryos /workspace/services /workspace/services

USER recoveryos
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os; os.kill(1, 0)"]
CMD ["python", "-m", "app.main"]
