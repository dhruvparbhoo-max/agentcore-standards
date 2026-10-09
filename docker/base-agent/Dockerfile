# syntax=docker/dockerfile:1.7
# Base for every agent runtime image. AgentCore Runtime runs ARM64; build with
# `docker buildx build --platform linux/arm64`. Both parents are pinned by digest
# (multi-arch index), so a rebuild never picks up a floating tag.
#
# Non-root user, /ping healthcheck, and OTEL_PYTHON_LOG_CORRELATION follow
# awslabs/fullstack-solution-template-for-agentcore
# patterns/strands-single-agent/Dockerfile (Apache-2.0, see NOTICE).
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE}
COPY --from=uv /uv /uvx /usr/local/bin/

# Prompt text, replies, and tool arguments stay out of spans and logs.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    DOCKER_CONTAINER=1 \
    OTEL_PYTHON_LOG_CORRELATION=true \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false \
    PATH=/app/.venv/bin:$PATH

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin bedrock_agentcore \
    && mkdir -p /app \
    && chown bedrock_agentcore /app
WORKDIR /app
USER bedrock_agentcore
EXPOSE 8080
