#!/usr/bin/env bash
# Attach the tigeri-app-profile IAM instance profile to an existing EC2 instance.
# Usage: ./attach_profile.sh i-0123456789abcdef0

set -euo pipefail

INSTANCE_ID="${1:?usage: $0 <instance-id>}"
PROFILE_NAME="${PROFILE_NAME:-tigeri-app-profile}"

EXISTING="$(aws ec2 describe-iam-instance-profile-associations \
    --filters "Name=instance-id,Values=${INSTANCE_ID}" \
    --query 'IamInstanceProfileAssociations[?State!=`disassociated`].AssociationId' \
    --output text)"

if [[ -n "$EXISTING" ]]; then
  echo "→ replacing existing association(s): $EXISTING"
  for assoc in $EXISTING; do
    aws ec2 replace-iam-instance-profile-association \
        --association-id "$assoc" \
        --iam-instance-profile "Name=${PROFILE_NAME}" \
        >/dev/null
  done
else
  aws ec2 associate-iam-instance-profile \
      --instance-id "$INSTANCE_ID" \
      --iam-instance-profile "Name=${PROFILE_NAME}" \
      >/dev/null
fi

echo "✓ profile $PROFILE_NAME associated with $INSTANCE_ID"
