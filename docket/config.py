"""Every value the container needs, read once at import."""

import os

# The proxy endpoint, never the instance. A failover then changes nothing here,
# because the proxy holds the client connection open through it.
DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
# The proxy is created with RequireTLS, so anything but require would be refused.
DB_SSL_MODE = os.environ.get("DB_SSL_MODE", "require")

REDIS_HOST = os.environ["REDIS_HOST"]
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_SSL = os.environ.get("REDIS_SSL", "true").lower() == "true"

# Small on purpose: the proxy owns pooling, and a large pool here just holds
# connections it would otherwise be free to share.
POOL_MIN = int(os.environ.get("POOL_MIN", "1"))
POOL_MAX = int(os.environ.get("POOL_MAX", "5"))

CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))
MAX_TITLE = 120
MAX_NOTES = 500

SKIP_SCHEMA = os.environ.get("SKIP_SCHEMA") == "1"
