# syntax=docker/dockerfile:1.7
# Toolchain image: the same container for a developer's editor, `make ci`, and
# the GitHub Actions jobs. Every parent is pinned by digest (multi-arch index),
# so the toolchain builds natively on arm64 and amd64.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a
ARG NODE_IMAGE=node:22.20.0-bookworm-slim@sha256:b21fe589dfbe5cc39365d0544b9be3f1f33f55f3c86c87a76ff65a02f8f5848e
ARG DOCKER_IMAGE=docker:28.5.1-cli@sha256:9190b0613792e658a7783cf14b2d5ace5941bb68ede7276922ea36ee457d76ad
ARG TRIVY_IMAGE=aquasec/trivy:0.67.2@sha256:e2b22eac59c02003d8749f5b8d9bd073b62e30fefaef5b7c8371204e0a4b0c08
ARG AWSCLI_IMAGE=amazon/aws-cli:2.31.13@sha256:e14216fb361cce909ce199616711ad103182d5937f851cda9bebf25867d7180a

FROM ${UV_IMAGE} AS uv
FROM ${NODE_IMAGE} AS node
FROM ${DOCKER_IMAGE} AS docker
FROM ${TRIVY_IMAGE} AS trivy
FROM ${AWSCLI_IMAGE} AS awscli

FROM ${PYTHON_IMAGE}
ARG AGENTCORE_CLI_VERSION=0.31.1
ARG CDK_CLI_VERSION=2.1145.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git make \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
COPY --from=awscli /usr/local/aws-cli /usr/local/aws-cli

RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s /usr/local/aws-cli/v2/current/bin/aws /usr/local/bin/aws \
    && npm install -g --no-audit --no-fund "@aws/agentcore@${AGENTCORE_CLI_VERSION}" "aws-cdk@${CDK_CLI_VERSION}" \
    && npm cache clean --force

ENV AGENTCORE_TELEMETRY_DISABLED=true \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN useradd --uid 1000 --create-home --shell /bin/bash dev \
    && mkdir -p /opt/venv \
    && chown dev /opt/venv
USER dev
WORKDIR /workspace
