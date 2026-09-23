"""Redis in front of the one query the page makes.

Read-through with whole-list invalidation. The list is small, and invalidation
that is obviously correct beats invalidation that is clever.
"""

import json
import logging

import redis

from . import config
from .db import Task

log = logging.getLogger(__name__)

KEY = "tasks:all"

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            ssl=config.REDIS_SSL,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
    return _client


def read() -> list[Task] | None:
    """None means a miss, or that Redis is unreachable and the caller should
    fall through to PostgreSQL rather than fail."""
    try:
        raw = get_client().get(KEY)
    except redis.RedisError as exc:
        log.warning("cache read failed, falling through: %s", exc)
        return None
    if raw is None:
        return None
    from datetime import datetime

    return [
        Task(r["id"], r["title"], r["notes"], r["done"], datetime.fromisoformat(r["created_at"]))
        for r in json.loads(raw)
    ]


def write(tasks: list[Task]) -> None:
    try:
        get_client().setex(KEY, config.CACHE_TTL, json.dumps([t.as_dict() for t in tasks]))
    except redis.RedisError as exc:
        log.warning("cache write failed: %s", exc)


def invalidate() -> None:
    """Called by every mutation. A write that forgets this is invisible until
    the TTL, which is the bug that looks like a slow database."""
    try:
        get_client().delete(KEY)
    except redis.RedisError as exc:
        log.warning("cache invalidate failed: %s", exc)


def reachable() -> bool:
    try:
        return bool(get_client().ping())
    except redis.RedisError as exc:
        log.warning("redis unreachable: %s", exc)
        return False
