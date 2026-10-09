#!/usr/bin/env bash
# Remove what scripts/deploy.sh created, in reverse order. Safe to run twice and
# safe to run after a failed deploy: every step tolerates a missing resource and
# the script keeps going, so a broken runtime never strands the foundation stack.
#
#   scripts/teardown.sh <pattern> <env>
#
# The AgentCore CLI removes resources by dropping them from the project and
# deploying the empty project (`agentcore remove all`, then `agentcore deploy`).
# CDK then destroys the foundation. In environments with `removal: retain` the
# KMS key, the log group, and the secrets stay behind on purpose.
set -uo pipefail

PATTERN="${1:?usage: scripts/teardown.sh <pattern> <env>}"
ENV_NAME="${2:?usage: scripts/teardown.sh <pattern> <env>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FOLDER="$ROOT/patterns/$PATTERN"
UV=(env -u VIRTUAL_ENV uv run --frozen)
cd "$ROOT"

read -r REGION PROJECT < <("${UV[@]}" python - "$FOLDER" "$ENV_NAME" "$ROOT" <<'PY'
import sys
from pathlib import Path
from agentcore_agent import load_pattern
from agentcore_agent.agentcore_json import project_name
from agentcore_agent.environment import load_environment
config = load_pattern(sys.argv[1])
print(load_environment(sys.argv[2], repo_root=Path(sys.argv[3])).region, project_name(config))
PY
)
export AWS_REGION="$REGION" CDK_DEFAULT_REGION="$REGION"
CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_ACCOUNT
PROJECT_DIR="$ROOT/build/deploy/$ENV_NAME/$PROJECT"
failed=0

if [ -d "$PROJECT_DIR/agentcore" ]; then
  echo "== agentcore resources"
  (cd "$PROJECT_DIR" && agentcore remove all -y && agentcore deploy -y --target "$ENV_NAME") || failed=1
else
  echo "no deploy project at $PROJECT_DIR; skipping AgentCore resources"
fi

echo "== foundation stack"
(cd "$FOLDER/infra" && npx --yes aws-cdk@2 destroy -c "env=$ENV_NAME" --force) || failed=1

if [ "$failed" -ne 0 ]; then
  echo "teardown finished with errors; re-run it, then check the console for leftovers" >&2
  exit 1
fi
echo "teardown of $PATTERN in $ENV_NAME complete"
