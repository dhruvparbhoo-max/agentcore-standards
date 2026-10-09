#!/usr/bin/env bash
# Deploy one pattern to one environment from a developer machine.
#
#   scripts/deploy.sh <pattern> <env>          e.g. scripts/deploy.sh _template dev
#
# 1. `docker ps`, doctor (read-only), and the production gate. Production refuses
#    to continue when a required control is missing.
# 2. CDK deploys the pattern foundation (KMS key, ECR repository with scan on push,
#    masked log group, secrets with rotation).
# 3. The base-agent image is built for linux/arm64 and pushed to that repository,
#    so CodeBuild can start the agent image FROM it.
# 4. The build-input digest and release id are computed, the deploy copy of
#    agentcore.json is rendered under build/deploy/ (outside git), and the
#    AgentCore CLI deploys it. The CLI builds the agent image in CodeBuild.
# 5. `agentcore-kit verify` compares the live runtime with pattern.yaml.
#
# ECR registry scanning (ENHANCED, scan on push) follows
# aws-samples/sample-bedrock-agentcore-runtime-cicd .github/workflows/deploy-agentcore.yml
# (MIT-0). Account ids come from STS at run time and are never written into git.
set -euo pipefail

PATTERN="${1:?usage: scripts/deploy.sh <pattern> <env>}"
ENV_NAME="${2:?usage: scripts/deploy.sh <pattern> <env>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER="${DOCKER:-docker}"
FOLDER="$ROOT/patterns/$PATTERN"
UV=(env -u VIRTUAL_ENV uv run --frozen)
KIT=("${UV[@]}" agentcore-kit --repo-root "$ROOT")
cd "$ROOT"

"$DOCKER" ps >/dev/null || { echo "'$DOCKER ps' failed: start Docker or Finch first" >&2; exit 1; }
"${KIT[@]}" doctor "$FOLDER" --env "$ENV_NAME"
"${KIT[@]}" production-check "$FOLDER" --env "$ENV_NAME"

read -r REGION PROJECT RUNTIME < <("${UV[@]}" python - "$FOLDER" "$ENV_NAME" "$ROOT" <<'PY'
import sys
from pathlib import Path
from agentcore_agent import load_pattern
from agentcore_agent.agentcore_json import project_name
from agentcore_agent.environment import load_environment
config = load_pattern(sys.argv[1])
environment = load_environment(sys.argv[2], repo_root=Path(sys.argv[3]))
print(environment.region, project_name(config), config.runtime_name)
PY
)
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export AWS_REGION="$REGION" CDK_DEFAULT_ACCOUNT="$ACCOUNT" CDK_DEFAULT_REGION="$REGION"
DEPLOY_DIR="$ROOT/build/deploy/$ENV_NAME"
mkdir -p "$DEPLOY_DIR"

echo "== foundation stack"
(cd "$FOLDER/infra" && npx --yes aws-cdk@2 deploy -c "env=$ENV_NAME" --require-approval never \
  --outputs-file "$DEPLOY_DIR/$PROJECT-foundation.json")
REPOSITORY_URI="$("${UV[@]}" python -c 'import json,sys; o=json.load(open(sys.argv[1])); print(next(v["RepositoryUri"] for v in o.values()))' "$DEPLOY_DIR/$PROJECT-foundation.json")"

echo "== registry scanning"
aws ecr put-registry-scanning-configuration --region "$REGION" --scan-type ENHANCED \
  --rules 'scanFrequency=SCAN_ON_PUSH,repositoryFilters=[{filter="*",filterType="WILDCARD"}]' >/dev/null \
  || echo "enhanced scanning not enabled; basic scan on push still applies"

echo "== base image"
aws ecr get-login-password --region "$REGION" | "$DOCKER" login --username AWS --password-stdin "${REPOSITORY_URI%%/*}"
BASE_TAG="base-agent-$(git hash-object docker/base-agent/Dockerfile | cut -c1-12)"
if ! aws ecr describe-images --region "$REGION" --repository-name "${REPOSITORY_URI#*/}" \
  --image-ids "imageTag=$BASE_TAG" >/dev/null 2>&1; then
  "$DOCKER" buildx build --platform linux/arm64 --provenance=false -t "$REPOSITORY_URI:$BASE_TAG" --push docker/base-agent
fi
BASE_DIGEST="$(aws ecr describe-images --region "$REGION" --repository-name "${REPOSITORY_URI#*/}" \
  --image-ids "imageTag=$BASE_TAG" --query 'imageDetails[0].imageDigest' --output text)"

echo "== release"
BUILD_DIGEST="$("${KIT[@]}" build-digest "$FOLDER" --base-digest "$BASE_DIGEST")"
RELEASE_ID="$("${KIT[@]}" release-id "$FOLDER" --image-digest "$BUILD_DIGEST" --inputs | tee /dev/stderr | head -1)"

PROJECT_DIR="$DEPLOY_DIR/$PROJECT"
if [ ! -d "$PROJECT_DIR/agentcore/cdk" ]; then
  agentcore create --name "$PROJECT" --no-agent --skip-git --skip-install --output-dir "$DEPLOY_DIR"
  (cd "$PROJECT_DIR/agentcore/cdk" && npm install --no-audit --no-fund)
fi
"${KIT[@]}" render-deploy "$FOLDER" --env "$ENV_NAME" --destination "$PROJECT_DIR" \
  --account "$ACCOUNT" --release-id "$RELEASE_ID" \
  --build-arg "BASE_AGENT_IMAGE=$REPOSITORY_URI@$BASE_DIGEST"

echo "== agentcore deploy"
(cd "$PROJECT_DIR" && agentcore validate && agentcore deploy -y --target "$ENV_NAME")

RUNTIME_ID="$("${UV[@]}" python - "$PROJECT_DIR/agentcore/.cli/deployed-state.json" "$ENV_NAME" "$RUNTIME" <<'PY'
import json, sys
state = json.load(open(sys.argv[1]))
print(state["targets"][sys.argv[2]]["resources"]["runtimes"][sys.argv[3]]["runtimeId"])
PY
)"

echo "== verify"
"${KIT[@]}" verify "$FOLDER" --runtime-id "$RUNTIME_ID" --release-id "$RELEASE_ID" \
  --endpoint "${ENDPOINT:-DEFAULT}" --region "$REGION"
echo "deployed $PATTERN release $RELEASE_ID to $ENV_NAME (runtime $RUNTIME_ID)"
