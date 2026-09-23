# Docket

A task list. Reads come from Redis, writes go to PostgreSQL through an RDS
Proxy. Flask, server-rendered, one container.

Infrastructure lives in [Docket-infra](https://github.com/sjamillah/Docket-infra).

## Running it locally

Needs PostgreSQL and Redis. Neither is mocked, because the caching behaviour is
the point of the application and a mock would not exercise it.

```bash
docker run -d --name docket-db -p 5432:5432 \
  -e POSTGRES_DB=docket -e POSTGRES_USER=docket -e POSTGRES_PASSWORD=docket postgres:16
docker run -d --name docket-redis -p 6379:6379 redis:7

DB_HOST=localhost DB_NAME=docket DB_USER=docket DB_PASSWORD=docket \
DB_SSL_MODE=disable REDIS_HOST=localhost REDIS_SSL=false \
python -m docket.app
```

Then <http://localhost:8080>.

```bash
ruff check . && ruff format --check . && pytest -q
```

These do not run in CI, which builds and ships only. Run them before you push.

## Layout

| Path | Holds |
|---|---|
| `docket/config.py` | Every value the container needs, read once at import |
| `docket/db.py` | The `Task` dataclass, the connection pool, the schema, and one query per operation |
| `docket/cache.py` | Redis in front of that query: read, write, invalidate, and a reachability probe |
| `docket/tasks.py` | The only module the views call. Reads try the cache, writes invalidate it |
| `docket/app.py` | The routes, and `/api/tasks` for proving the cache works |
| `docket/templates/`, `docket/static/` | One page and one stylesheet |
| `deploy/` | `taskdef.json` and `appspec.yaml`, rendered by CI and read by CodeDeploy |

## How the caching works

`tasks.all_tasks()` reads through `cache`. The first call after a write
queries PostgreSQL and stores the result under `tasks:all`; every call after
that is answered by Redis until something changes.

Every mutation in `tasks.py` calls `cache.invalidate()` on the same key.
Whole-list invalidation rather than patching the cached list: the list is
small, and invalidation that is obviously correct beats invalidation that is
clever.

`test_every_mutation_invalidates` is parametrised over every public mutation
in `tasks.py` and fails if one does not evict the key. A mutation added
without an eviction would otherwise be invisible until the TTL expired, which
is the kind of bug that looks like "the database is slow to update".

A Redis outage is survivable in both directions: `cache.read()` returns `None`
and the caller falls through to PostgreSQL, and every write path logs and
continues.

To see it working:

```bash
curl -s "$URL/api/tasks" | head -c 200     # first call populates
curl -s "$URL/api/tasks" | head -c 200     # served from Redis
```

Then watch `CacheHitRate` in CloudWatch, which has an alarm on it.

## Health checks

Two endpoints, and the split is deliberate.

| Endpoint | Checks | Used by |
|---|---|---|
| `/health` | nothing external | the ALB target group and the container health check |
| `/ready` | the database and Redis | humans, and a canary if one is ever added |

The target group uses `/health`. A deep check there would fail every target at
once during an RDS failover and turn a short blip into an outage — which is
exactly what the proxy exists to prevent.

`/ready` returns 503 only when PostgreSQL is unreachable. Redis being down is
reported as `degraded` with a 200, because reads still work.

## Deployment

One workflow, one job, three steps. It runs on pushes to `main` and does
nothing else:

| Step | Does |
|---|---|
| Build | `docker build` |
| Publish deploy config | renders `taskdef.json`, zips it with `appspec.yaml`, uploads it |
| Push image | moves `:latest` in ECR |

The order is the point. Moving `:latest` is what fires the EventBridge rule
that starts the pipeline, so the descriptors have to be in place before the
image lands — publish, then push.

Authentication is OIDC; there are no AWS access keys anywhere.

**There is no test gate.** Linting, the unit tests and the smoke test are
local commands, listed under Running it above. If you want one back, it is a
step, not a job.

Two repository settings, and neither is an account identifier:

| Name | Kind | Source |
|---|---|---|
| `AWS_ROLE_ARN` | secret | `/docket/gha-app-role-arn` |
| `AWS_REGION` | variable | the deployment region |

The ECR repository name, the artifact bucket, both task role ARNs, the proxy
and cache endpoints and the database secret ARN are all resolved from
Parameter Store at build time.

### How `deploy/taskdef.json` is filled in

CodeDeploy reads a complete task definition from the pipeline's source
artifact and substitutes nothing but `<IMAGE1_NAME>`. Everything else — role
ARNs, endpoints, the secret ARN, the region — has to already be in the file,
and none of it exists until the infrastructure is up.

So the committed file carries placeholders, and
the workflow's **Publish deploy config** step renders them on every build:

| Placeholder | Published by |
|---|---|
| `<TASK_ROLE_ARN>`, `<EXECUTION_ROLE_ARN>` | `templates/iam.yaml` |
| `<DB_PROXY_ENDPOINT>`, `<DB_SECRET_ARN>` | `templates/database.yaml` |
| `<CACHE_ENDPOINT>` | `templates/cache.yaml` |
| `<AWS_REGION>` | the workflow's own region |
| `<IMAGE1_NAME>` | left alone — CodeDeploy fills it with the image digest |

The script fails if any placeholder but `<IMAGE1_NAME>` survives, so a missing
parameter stops the build rather than producing a task definition that
registers and then cannot start.

**`environment` and `secrets` mirror `ContainerDefinitions` in the
infrastructure repository's `templates/service.yaml`.** CloudFormation
registers the first revision from that template; every later revision comes
from this file. If you add a variable in one, add it in the other, or the
first blue/green deployment will quietly drop it.

There is no script to run locally: the substitution is six `sed` expressions
in the workflow, and reading it there is the documentation.

### Deploying a config-only change

The pipeline's S3 source sets `PollForSourceChanges: false`, so uploading a new
`deploy.zip` does not start anything — only an image push does. After a change
that touches `deploy/` alone:

```bash
aws codepipeline start-pipeline-execution --name docket-pipeline
```

Not the retry arrow on the failed stage: it replays the same source revision,
which is the one you just replaced.

**Rebuilding the database changes the secret ARN.** Nothing needs regenerating
by hand — `database.yaml` republishes `/docket/db-secret-arn`, and the next
build picks it up. Until that build runs, tasks fail with
`ResourceInitializationError: unable to pull secrets`, an *AccessDenied*
rather than a *NotFound*, because the execution role is scoped to the real
secret.

## Diagnosing a stuck deployment

Step 1 stalling at 50% means the green task set started but its tasks are not
becoming healthy.

```bash
aws ecs describe-tasks --cluster docket-cluster --region $R \
  --tasks $(aws ecs list-tasks --cluster docket-cluster --desired-status STOPPED \
            --region $R --query 'taskArns[]' --output text) \
  --query 'tasks[].{stopped:stoppedReason,container:containers[0].reason}' --output json
```

| Message | Cause |
|---|---|
| `unable to pull secrets` | stale secret ARN — rerun the build, which re-resolves it |
| `unable to pull image` | no route to ECR; check the `ecr.api` and `ecr.dkr` endpoints |
| `failed ELB health checks` | the container is up but liveness is not answering on 8080 |
| `Essential container ... exited` | read `/ecs/docket`; usually `create_schema()` cannot reach the proxy |

Cluster is `docket-cluster`, service `docket-service`, task definition family
and log group both plain `docket`.

## Notes on the design

**The pool is capped at five connections.** `POOL_MAX` in `config.py`. The
proxy owns pooling; a large pool in the task just holds connections the proxy
would otherwise be free to share, which defeats the point of having it.

**The image is layered.** `pyproject.toml` is copied and the dependencies
installed before the application code, so a code change rebuilds one thin
layer rather than reinstalling Flask and psycopg every time.

**No curl in the image.** The container health check shells out to `python`,
which is already there, so nothing is installed on top of the base image.

**`CREATE TABLE IF NOT EXISTS` rather than a migration tool.** One table and
one index do not justify one, and `IF NOT EXISTS` throughout is what makes two
tasks starting simultaneously harmless. `SKIP_SCHEMA=1` skips it entirely,
which is how the image runs without a database.

## Known gaps

- There is no migration history. `create_schema()` is additive only, so a
  column that needs changing needs doing by hand.
- The base image is pinned by tag, not digest, so two builds a week apart can
  differ. ECR scan-on-push covers the OS packages.
- Nothing scans the Python dependencies. Inspector enhanced scanning on the
  registry is the AWS-side answer.
- CI does not run the tests. `ruff` and `pytest` are local commands.
- No rate limiting. With no accounts, the only limits are the task count and
  whatever the ALB allows.
