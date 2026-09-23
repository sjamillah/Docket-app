#!/usr/bin/env bash
# Render deploy/taskdef.json and hand it, with appspec.yaml, to the pipeline.
#
# CodeDeploy substitutes nothing but <IMAGE1_NAME>, so the task definition it
# reads has to be complete: role ARNs, the proxy and cache endpoints, and the
# secret ARN. None of those exist until the infrastructure is up, and none of
# them belong in git.
#
# Each one is published to Parameter Store by the stack that creates it, so
# this resolves them rather than having them pasted in. CodePipeline reads the
# zip this uploads; it does not read this repository, which is why the app
# owns its own deploy descriptors.
#
#   scripts/publish-deploy-config.sh
set -euo pipefail

PROJECT="${PROJECT:-docket}"
region="${AWS_REGION:?AWS_REGION is not set}"

param() {
  aws ssm get-parameter --name "/$PROJECT/$1" --query Parameter.Value --output text
}

bucket="$(param artifact-bucket)"
task_role="$(param task-role-arn)"
exec_role="$(param task-execution-role-arn)"
db_endpoint="$(param db-proxy-endpoint)"
db_secret="$(param db-secret-arn)"
cache_endpoint="$(param cache-endpoint)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

sed -e "s|<TASK_ROLE_ARN>|$task_role|g" \
    -e "s|<EXECUTION_ROLE_ARN>|$exec_role|g" \
    -e "s|<AWS_REGION>|$region|g" \
    -e "s|<DB_PROXY_ENDPOINT>|$db_endpoint|g" \
    -e "s|<DB_SECRET_ARN>|$db_secret|g" \
    -e "s|<CACHE_ENDPOINT>|$cache_endpoint|g" \
    deploy/taskdef.json > "$work/taskdef.json"

# <IMAGE1_NAME> is deliberately left: CodeDeploy replaces it with the digest
# from imageDetail.json, so the deployed revision names an image by digest.
if grep -o '<[A-Z0-9_]*>' "$work/taskdef.json" | grep -qv '<IMAGE1_NAME>'; then
  echo "a placeholder survived substitution:" >&2
  grep -o '<[A-Z0-9_]*>' "$work/taskdef.json" | grep -v '<IMAGE1_NAME>' >&2
  exit 1
fi
python -c 'import json,sys; json.load(open(sys.argv[1]))' "$work/taskdef.json"

cp deploy/appspec.yaml "$work/appspec.yaml"

# Flat: the pipeline's TaskDefinitionTemplatePath is taskdef.json, not
# deploy/taskdef.json, because the zip root is what it unpacks.
(cd "$work" && zip -q deploy.zip taskdef.json appspec.yaml)

aws s3 cp "$work/deploy.zip" "s3://$bucket/config/deploy.zip"

echo "published s3://$bucket/config/deploy.zip"
