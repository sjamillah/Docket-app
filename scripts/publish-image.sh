#!/usr/bin/env bash
# Move the one tag this project uses. Pushing :latest is what fires the
# EventBridge rule; the pipeline reads the digest out of imageDetail.json, so
# nothing here needs to look it up.
#
#   scripts/publish-image.sh ci-candidate <registry> <repository>
set -euo pipefail

LOCAL="${1:?usage: publish-image.sh <local-image> <registry> <repository>}"
REGISTRY="${2:?missing registry}"
REPOSITORY="${3:?missing repository}"

remote="$REGISTRY/$REPOSITORY"

docker tag "$LOCAL" "$remote:latest"
docker push "$remote:latest"

echo "published $remote:latest"
