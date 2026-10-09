# syntax=docker/dockerfile:1.7
# One image for the front door's handlers (chat and job). Build context is the
# repo root. The builder resolves the frozen workspace lock for this package only;
# the final stage copies the installed packages into the Lambda task root.
# Code stays root-owned; Lambda runs it as a non-root user.
ARG BASE_LAMBDA_IMAGE=agentcore-standards/base-lambda:local

FROM ${BASE_LAMBDA_IMAGE} AS builder
USER root
WORKDIR /src
COPY . .
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package agentcore-front-door

FROM ${BASE_LAMBDA_IMAGE}
COPY --from=builder /opt/venv/lib/python3.12/site-packages ${LAMBDA_TASK_ROOT}
CMD ["agentcore_front_door.handlers.chat.handler"]
