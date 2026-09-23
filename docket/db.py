"""PostgreSQL, reached through the RDS Proxy."""

import logging
from dataclasses import dataclass
from datetime import datetime

from psycopg.rows import class_row
from psycopg_pool import ConnectionPool

from . import config

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         BIGSERIAL PRIMARY KEY,
    title      VARCHAR(120) NOT NULL,
    notes      VARCHAR(500),
    done       BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS tasks_done_created_idx ON tasks (done ASC, created_at DESC);
"""


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    notes: str | None
    done: bool
    created_at: datetime

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "notes": self.notes,
            "done": self.done,
            "created_at": self.created_at.isoformat(),
        }


_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        conninfo = (
            f"host={config.DB_HOST} port={config.DB_PORT} dbname={config.DB_NAME} "
            f"user={config.DB_USER} password={config.DB_PASSWORD} "
            f"sslmode={config.DB_SSL_MODE}"
        )
        _pool = ConnectionPool(
            conninfo,
            min_size=config.POOL_MIN,
            max_size=config.POOL_MAX,
            # Do not block startup on the database; /health stays shallow so the
            # task can come up and report why it cannot connect.
            open=False,
            timeout=10,
        )
        _pool.open()
    return _pool


def create_schema() -> None:
    """IF NOT EXISTS throughout, so two tasks starting together is harmless."""
    with get_pool().connection() as conn:
        conn.execute(SCHEMA)


def all_tasks() -> list[Task]:
    with get_pool().connection() as conn, conn.cursor(row_factory=class_row(Task)) as cur:
        cur.execute(
            "SELECT id, title, notes, done, created_at FROM tasks "
            "ORDER BY done ASC, created_at DESC"
        )
        return cur.fetchall()


def add(title: str, notes: str | None) -> None:
    with get_pool().connection() as conn:
        conn.execute("INSERT INTO tasks (title, notes) VALUES (%s, %s)", (title, notes))


def toggle(task_id: int) -> None:
    with get_pool().connection() as conn:
        conn.execute("UPDATE tasks SET done = NOT done WHERE id = %s", (task_id,))


def edit(task_id: int, title: str, notes: str | None) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE tasks SET title = %s, notes = %s WHERE id = %s", (title, notes, task_id)
        )


def delete(task_id: int) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM tasks WHERE id = %s", (task_id,))


def reachable() -> bool:
    try:
        with get_pool().connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("database unreachable: %s", exc)
        return False
