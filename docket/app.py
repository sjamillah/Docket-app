"""Docket - a task list. Reads from Redis, writes through RDS Proxy."""

import logging
import os

from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import cache, config, db, tasks

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("docket")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

if not config.SKIP_SCHEMA:
    try:
        db.create_schema()
    except Exception as exc:  # noqa: BLE001
        # Staying up keeps /health passing and puts the reason in CloudWatch,
        # which beats a crash loop that says nothing.
        log.error("could not create the schema at start: %s", exc)


# --- Health -------------------------------------------------------------


@app.get("/health")
def health():
    """What the target group polls.

    Deliberately touches neither backend. A deep check here would fail every
    target at once during an RDS failover and turn a blip into an outage.
    """
    return {"status": "ok"}, 200


@app.get("/ready")
def ready():
    database, redis_up = db.reachable(), cache.reachable()
    body = {
        "status": "ok" if database and redis_up else "degraded",
        "database": "reachable" if database else "unreachable",
        "cache": "reachable" if redis_up else "unreachable",
    }
    # The cache going down is survivable; reads fall through to PostgreSQL.
    return body, 200 if database else 503


# --- Pages --------------------------------------------------------------


@app.get("/")
def index():
    items = tasks.all_tasks()
    return render_template("index.html", tasks=items, open=sum(1 for t in items if not t.done))


@app.post("/tasks")
def create():
    title = (request.form.get("title") or "").strip()
    if title:
        tasks.add(title[: config.MAX_TITLE], _notes())
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/toggle")
def toggle(task_id: int):
    tasks.toggle(task_id)
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/edit")
def edit(task_id: int):
    title = (request.form.get("title") or "").strip()
    if title:
        tasks.edit(task_id, title[: config.MAX_TITLE], _notes())
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/delete")
def delete(task_id: int):
    tasks.delete(task_id)
    return redirect(url_for("index"))


# Proves the cache is doing something, which the page cannot show on its own.
@app.get("/api/tasks")
def api():
    return jsonify([t.as_dict() for t in tasks.all_tasks()])


def _notes() -> str | None:
    notes = (request.form.get("notes") or "").strip()
    return notes[: config.MAX_NOTES] or None
