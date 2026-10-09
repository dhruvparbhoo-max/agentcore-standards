# syntax=docker/dockerfile:1.7
# Rotation Lambda image. Build context is infra/rotation. boto3 comes with the pinned base.
ARG BASE_LAMBDA_IMAGE=agentcore-standards/base-lambda:local
FROM ${BASE_LAMBDA_IMAGE}
COPY handler.py ${LAMBDA_TASK_ROOT}/rotation_handler.py
CMD ["rotation_handler.handler"]
