"""The cache is only correct if every write invalidates what the read stores."""

import inspect
from datetime import UTC, datetime

import pytest

from docket import cache, db, tasks


@pytest.fixture
def sample():
    return [db.Task(1, "Renew the domain", "before the 30th", False, datetime.now(UTC))]


def test_read_falls_through_to_postgres_on_a_miss(monkeypatch, sample):
    monkeypatch.setattr(cache, "read", lambda: None)
    monkeypatch.setattr(db, "all_tasks", lambda: sample)
    written = []
    monkeypatch.setattr(cache, "write", written.append)

    assert tasks.all_tasks() == sample
    assert written == [sample], "a miss must populate the cache"


def test_read_does_not_touch_postgres_on_a_hit(monkeypatch, sample):
    monkeypatch.setattr(cache, "read", lambda: sample)

    def explode():
        raise AssertionError("a cache hit must not query PostgreSQL")

    monkeypatch.setattr(db, "all_tasks", explode)
    assert tasks.all_tasks() == sample


@pytest.mark.parametrize("name", ["add", "toggle", "edit", "delete"])
def test_every_mutation_invalidates(monkeypatch, name):
    """A write added without an invalidation is invisible until the TTL, which
    is the bug that looks like a slow database."""
    calls = []
    monkeypatch.setattr(cache, "invalidate", lambda: calls.append(name))
    monkeypatch.setattr(db, name, lambda *a, **k: None)

    fn = getattr(tasks, name)
    args = [a for a in inspect.signature(fn).parameters]
    fn(*[1 if a.endswith("id") else "x" for a in args])

    assert calls == [name], f"{name} must invalidate the cache"


def test_a_broken_cache_does_not_break_reads(monkeypatch, sample):
    """Redis is an accelerator, not a dependency."""
    import redis

    def boom(*_a, **_k):
        raise redis.RedisError("down")

    monkeypatch.setattr(cache, "get_client", boom)
    monkeypatch.setattr(db, "all_tasks", lambda: sample)
    assert tasks.all_tasks() == sample
