# syntax=docker/dockerfile:1.7
ARG BASE_AGENT_IMAGE=agentcore-standards/base-agent:local

FROM ${BASE_AGENT_IMAGE} AS builder
USER root
WORKDIR /src
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package pattern-human-approval-agent

FROM ${BASE_AGENT_IMAGE}
COPY --from=builder /app/.venv /app/.venv
COPY patterns/human-approval/pattern.yaml /app/patterns/human-approval/pattern.yaml
COPY patterns/human-approval/prompts /app/patterns/human-approval/prompts
COPY patterns/human-approval/policies /app/patterns/human-approval/policies
COPY patterns/human-approval/schemas /app/patterns/human-approval/schemas
COPY patterns/human-approval/agent/main.py /app/main.py
COPY primitives/gateway-tools/submit_change/submit_change /app/submit_change
ENV AGENTCORE_PATTERN_DIR=/app/patterns/human-approval \
    AGENTCORE_PATTERN=human-approval \
    PYTHONPATH=/app

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping', timeout=2)" || exit 1

CMD ["python", "main.py"]
