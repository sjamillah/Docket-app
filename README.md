# Docket

A task list. Reads come from Redis, writes go to PostgreSQL through an RDS
Proxy. Spring Boot, server-rendered, one container.

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
bash scripts/smoke-test.sh "$(docker build -q .)"
```

Neither runs in CI, which builds and ships only. Run them before you push.

## Layout

| Path | Holds |
|---|---|
| `Task.java` | A record. Serialised into Redis, so it stays plain data |
| `TaskRepository.java` | One query, in the order the page asks for |
| `TaskService.java` | Where the caching lives: `@Cacheable` on the read, `@CacheEvict` on every write |
| `CacheConfig.java` | JSON serialisation and a one-hour backstop TTL |
| `TaskController.java` | The pages, and `/api/tasks` for proving the cache works |
| `db/migration/V1__tasks.sql` | Flyway. One table, one index |
| `deploy/` | `taskdef.json` and `appspec.yaml`, rendered by CI and read by CodeDeploy |

## How the caching works

`TaskService.all()` is `@Cacheable`. The first read after a write queries
PostgreSQL and stores the result; every read after that is answered by Redis
until something changes.

Every mutating method carries `@CacheEvict` on the same key. Whole-list
eviction rather than patching the cached list: the list is small, and eviction
that is obviously correct beats eviction that is clever.

`CacheKeyTest` asserts that relationship by reflection — it reads the
`@Cacheable` key off the read method and fails if any public mutating method
does not evict exactly it. A new mutation added without an eviction would
otherwise be invisible until the TTL expired, which is the kind of bug that
looks like "the database is slow to update".

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
| `/actuator/health/liveness` | nothing external | the ALB target group and the container health check |
| `/actuator/health/readiness` | the database and Redis | humans, and a canary if one is ever added |

The target group uses **liveness**. A deep check there would fail every target
at once during an RDS failover and turn a short blip into an outage — which is
exactly what the proxy exists to prevent.

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
`scripts/publish-deploy-config.sh` renders them on every build:

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

To try it locally, with credentials that can read `/docket/*`:

```bash
AWS_REGION=$(aws configure get region) bash scripts/publish-deploy-config.sh
```

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
| `Essential container ... exited` | read `/ecs/docket`; usually Flyway cannot reach the proxy |

Cluster is `docket-cluster`, service `docket-service`, task definition family
and log group both plain `docket`.

## Notes on the design

**Hikari is capped at five connections.** The proxy owns pooling; a large pool
in the task just holds connections the proxy would otherwise be free to share,
which defeats the point of having it.

**The image is layered.** `spring-boot-maven-plugin` splits dependencies from
application code, so a code change rebuilds one thin layer rather than shipping
the JVM and every jar again.

**`MaxRAMPercentage=70`.** Fargate gives the container a hard memory limit, and
without this the JVM sizes its heap from the host and gets killed.

**Flyway rather than schema-on-start.** It records what it ran, which is what
makes two tasks starting simultaneously harmless.

## Known gaps

- Schema changes are forward-only; there are no down migrations.
- The base image is pinned by tag, not digest, so two builds a week apart can
  differ. ECR scan-on-push covers the OS packages.
- Nothing scans the Java dependencies. Inspector enhanced scanning on the
  registry is the AWS-side answer.
- No rate limiting. With no accounts, the only limits are the task count and
  whatever the ALB allows.
