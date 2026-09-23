"""Reads come from Redis, writes go to PostgreSQL through the proxy."""

from . import cache, db
from .db import Task


def all_tasks() -> list[Task]:
    cached = cache.read()
    if cached is not None:
        return cached
    tasks = db.all_tasks()
    cache.write(tasks)
    return tasks


def add(title: str, notes: str | None) -> None:
    db.add(title, notes)
    cache.invalidate()


def toggle(task_id: int) -> None:
    db.toggle(task_id)
    cache.invalidate()


def edit(task_id: int, title: str, notes: str | None) -> None:
    db.edit(task_id, title, notes)
    cache.invalidate()


def delete(task_id: int) -> None:
    db.delete(task_id)
    cache.invalidate()
