"""Set the environment the application reads at import time."""

import os

os.environ.setdefault("DB_HOST", "db.test.invalid")
os.environ.setdefault("DB_NAME", "docket")
os.environ.setdefault("DB_USER", "docket")
os.environ.setdefault("DB_PASSWORD", "docket")
os.environ.setdefault("REDIS_HOST", "redis.test.invalid")
os.environ.setdefault("REDIS_SSL", "false")
os.environ.setdefault("SKIP_SCHEMA", "1")
