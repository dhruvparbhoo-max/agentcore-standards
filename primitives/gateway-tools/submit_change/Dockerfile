# syntax=docker/dockerfile:1.7
ARG BASE_LAMBDA_IMAGE=agentcore-standards/base-lambda:local
FROM ${BASE_LAMBDA_IMAGE}
COPY primitives/gateway-tools/submit_change/submit_change ${LAMBDA_TASK_ROOT}/submit_change
CMD ["submit_change.handler.handler"]
