# syntax=docker/dockerfile:1.7
# Base for Lambda images (triggers, front door, approvals) and for Gateway tools
# whose dependencies match. Each unit's Dockerfile names its handler with CMD.
# Both parents are pinned by digest. Lambda runs the handler as a non-root user;
# USER 10001 makes the local container match.
ARG LAMBDA_IMAGE=public.ecr.aws/lambda/python:3.12@sha256:d0a4fa8f489a7d9f05a95e642ffd599bea3b07339adb510185a8a14653944b1c
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a

FROM ${UV_IMAGE} AS uv

FROM ${LAMBDA_IMAGE}
COPY --from=uv /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/var/lang/bin/python3.12 \
    OTEL_PYTHON_LOG_CORRELATION=true \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false

USER 10001
