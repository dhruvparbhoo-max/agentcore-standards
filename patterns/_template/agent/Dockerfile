# syntax=docker/dockerfile:1.7
# Build context is the repo root (agentcore.json buildContextPath "../..").
# The builder resolves the frozen workspace lock; the final stage copies only
# the virtualenv and the pattern files. Code stays root-owned; the process runs
# as the base image's non-root user.
ARG BASE_AGENT_IMAGE=agentcore-standards/base-agent:local

FROM ${BASE_AGENT_IMAGE} AS builder
USER root
WORKDIR /src
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package pattern-template-agent

FROM ${BASE_AGENT_IMAGE}
COPY --from=builder /app/.venv /app/.venv
COPY patterns/_template/pattern.yaml /app/patterns/_template/pattern.yaml
COPY patterns/_template/prompts /app/patterns/_template/prompts
COPY patterns/_template/policies /app/patterns/_template/policies
COPY patterns/_template/schemas /app/patterns/_template/schemas
COPY patterns/_template/agent/main.py /app/main.py
ENV AGENTCORE_PATTERN_DIR=/app/patterns/_template \
    AGENTCORE_PATTERN=_template

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping', timeout=2)" || exit 1

CMD ["python", "main.py"]
