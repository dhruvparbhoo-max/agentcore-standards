# syntax=docker/dockerfile:1.7
# Build context is the repo root (agentcore.json buildContextPath "../..").
ARG BASE_AGENT_IMAGE=agentcore-standards/base-agent:local

FROM ${BASE_AGENT_IMAGE} AS builder
USER root
WORKDIR /src
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package pattern-policy-qa-agent

FROM ${BASE_AGENT_IMAGE}
COPY --from=builder /app/.venv /app/.venv
COPY patterns/policy-qa/pattern.yaml /app/patterns/policy-qa/pattern.yaml
COPY patterns/policy-qa/prompts /app/patterns/policy-qa/prompts
COPY patterns/policy-qa/policies /app/patterns/policy-qa/policies
COPY patterns/policy-qa/schemas /app/patterns/policy-qa/schemas
COPY patterns/policy-qa/agent/main.py /app/main.py
ENV AGENTCORE_PATTERN_DIR=/app/patterns/policy-qa \
    AGENTCORE_PATTERN=policy-qa

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping', timeout=2)" || exit 1

CMD ["python", "main.py"]
