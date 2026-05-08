#!/usr/bin/env bash
# One-shot IAM setup. Creates a role + instance profile and attaches a policy
# scoped to the Tigeri S3 Express (Directory) bucket. Idempotent.
#
# Required env vars:
#   TIGERI_S3_DOCUMENTS_BUCKET   the existing directory bucket name
#                                e.g. trigeri--global--use1-az4--x-s3
#   AWS_REGION                   e.g. us-east-1
#   AWS_ACCOUNT_ID               e.g. 596871238695
#
# Optional:
#   ROLE_NAME                    default: tigeri-app-role
#   PROFILE_NAME                 default: tigeri-app-profile

set -euo pipefail

: "${TIGERI_S3_DOCUMENTS_BUCKET:?must be set}"
: "${AWS_REGION:?must be set}"
: "${AWS_ACCOUNT_ID:?must be set}"

ROLE_NAME="${ROLE_NAME:-tigeri-app-role}"
PROFILE_NAME="${PROFILE_NAME:-tigeri-app-profile}"
POLICY_NAME="tigeri-app-policy"

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP_POLICY="$(mktemp)"
trap 'rm -f "$TMP_POLICY"' EXIT

sed \
  -e "s|REPLACE_WITH_BUCKET_NAME|${TIGERI_S3_DOCUMENTS_BUCKET}|g" \
  -e "s|REPLACE_WITH_REGION|${AWS_REGION}|g" \
  -e "s|REPLACE_WITH_ACCOUNT_ID|${AWS_ACCOUNT_ID}|g" \
  "$HERE/iam_policy.json" > "$TMP_POLICY"

echo "→ creating role $ROLE_NAME"
aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$HERE/iam_trust.json" \
    >/dev/null 2>&1 || echo "  (role exists, continuing)"

echo "→ putting inline policy $POLICY_NAME"
aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME" \
    --policy-document "file://$TMP_POLICY"

echo "→ creating instance profile $PROFILE_NAME"
aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" \
    >/dev/null 2>&1 || echo "  (profile exists, continuing)"

aws iam add-role-to-instance-profile \
    --instance-profile-name "$PROFILE_NAME" \
    --role-name "$ROLE_NAME" \
    >/dev/null 2>&1 || echo "  (role already in profile)"

echo "✓ done. Profile name: $PROFILE_NAME"
echo "  Next: ./attach_profile.sh <ec2-instance-id>"
