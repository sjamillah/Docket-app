#!/usr/bin/env bash
# Start the built image and wait for it to serve /health. Needs no AWS, no
# database and no Redis, because /health is deliberately shallow.
#
#   scripts/smoke-test.sh ci-candidate
set -euo pipefail

IMAGE="${1:?usage: smoke-test.sh <image>}"
PORT="${PORT:-8080}"
CONTAINER=ci-smoke

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$CONTAINER" -p "$PORT:8080" \
  -e DB_HOST=localhost -e DB_NAME=x -e DB_USER=x -e DB_PASSWORD=x \
  -e REDIS_HOST=localhost -e REDIS_SSL=false -e SKIP_SCHEMA=1 \
  "$IMAGE" >/dev/null

if ! timeout 40 sh -c "until curl -fsS http://localhost:$PORT/health >/dev/null 2>&1; do sleep 1; done"; then
  echo "container never became healthy" >&2
  docker logs "$CONTAINER" >&2
  exit 1
fi

uid="$(docker run --rm "$IMAGE" id -u)"
[ "$uid" != "0" ] || { echo "image runs as root" >&2; exit 1; }

echo "healthy, running as uid $uid"
