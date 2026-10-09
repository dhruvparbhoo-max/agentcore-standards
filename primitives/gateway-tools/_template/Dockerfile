# syntax=docker/dockerfile:1.7
# One image per Gateway tool, so its permissions and dependencies stay its own.
# Build context is the repo root. The tool needs only boto3, which the pinned
# Lambda base already carries, so there is nothing to sync.
ARG BASE_LAMBDA_IMAGE=agentcore-standards/base-lambda:local
FROM ${BASE_LAMBDA_IMAGE}
COPY primitives/gateway-tools/_template/template_tool ${LAMBDA_TASK_ROOT}/template_tool
CMD ["template_tool.handler.handler"]
