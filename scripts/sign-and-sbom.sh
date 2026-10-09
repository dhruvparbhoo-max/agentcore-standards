#!/usr/bin/env bash
# Sign, verify, and export an SBOM for one pushed image. Fails closed.
#
#   scripts/sign-and-sbom.sh <repository-name> <image-digest>
#
# Environment (names only; values come from the shell or the CI secret store):
#   AWS_REGION            region of the repository
#   SIGNING_PROFILE_ARN   AWS Signer profile ECR managed signing uses
#   SBOM_BUCKET           S3 bucket for Inspector SBOM exports
#   SBOM_KMS_KEY_ARN      KMS key Inspector encrypts the export with
#
# No AgentCore sample signs images or exports an SBOM (production readiness
# references, item 2 gap). This follows the AWS docs the references name:
#   - ECR managed signing: put-signing-configuration, describe-image-signing-status
#     https://docs.aws.amazon.com/AmazonECR/latest/userguide/managed-signing.html
#   - AgentCore Runtime does not verify signatures, so `notation verify` runs here,
#     before the digest is handed to a build or a runtime update.
#   - Inspector SBOM export: create-sbom-export (needs ENHANCED scanning, which
#     scripts/deploy.sh turns on).
#     https://docs.aws.amazon.com/inspector/latest/user/sbom-export.html
set -euo pipefail

REPOSITORY="${1:?usage: scripts/sign-and-sbom.sh <repository-name> <image-digest>}"
DIGEST="${2:?usage: scripts/sign-and-sbom.sh <repository-name> <image-digest>}"
: "${AWS_REGION:?set AWS_REGION}" "${SIGNING_PROFILE_ARN:?set SIGNING_PROFILE_ARN}"
: "${SBOM_BUCKET:?set SBOM_BUCKET}" "${SBOM_KMS_KEY_ARN:?set SBOM_KMS_KEY_ARN}"
case "$DIGEST" in sha256:*) ;; *) echo "image digest must be sha256:..., not a tag" >&2; exit 1 ;; esac

echo "== managed signing for $REPOSITORY"
aws ecr put-signing-configuration --region "$AWS_REGION" --signing-configuration \
  "{\"rules\":[{\"signingProfileArn\":\"$SIGNING_PROFILE_ARN\",\"repositoryFilters\":[{\"filter\":\"$REPOSITORY\",\"filterType\":\"WILDCARD_MATCH\"}]}]}" \
  >/dev/null

status=""
for _ in $(seq 1 30); do
  status="$(aws ecr describe-image-signing-status --region "$AWS_REGION" --repository-name "$REPOSITORY" \
    --image-id "imageDigest=$DIGEST" --query 'signingStatuses[0].status' --output text 2>/dev/null || true)"
  [ "$status" = "COMPLETE" ] && break
  [ "$status" = "FAILED" ] && { echo "ECR signing failed for $DIGEST" >&2; exit 1; }
  sleep 10
done
[ "$status" = "COMPLETE" ] || { echo "image $DIGEST is not signed (status: ${status:-none})" >&2; exit 1; }

echo "== notation verify"
REGISTRY="$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$AWS_REGION.amazonaws.com"
command -v notation >/dev/null || { echo "notation is not installed; refusing to continue unverified" >&2; exit 1; }
notation verify "$REGISTRY/$REPOSITORY@$DIGEST"

echo "== SBOM export"
aws inspector2 create-sbom-export --region "$AWS_REGION" --report-format CYCLONEDX_1_4 \
  --resource-filter-criteria "{\"ecrRepositoryName\":[{\"comparison\":\"EQUALS\",\"value\":\"$REPOSITORY\"}]}" \
  --s3-destination "bucketName=$SBOM_BUCKET,keyPrefix=sbom/$REPOSITORY/${DIGEST#sha256:},kmsKeyArn=$SBOM_KMS_KEY_ARN" \
  --query reportId --output text
echo "signed, verified, and SBOM export started for $REPOSITORY@$DIGEST"
