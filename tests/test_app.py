from datetime import UTC, datetime

import pytest

from docket import app as app_module
from docket import db, tasks


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        tasks,
        "all_tasks",
        lambda: [
            db.Task(
                1, "Renew the domain", "before the 30th", False, datetime(2026, 9, 13, tzinfo=UTC)
            ),
            db.Task(2, "Cancel the trial", None, True, datetime(2026, 9, 12, tzinfo=UTC)),
        ],
    )
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_health_is_shallow(client, monkeypatch):
    """It must answer with both backends down, which is why the target group
    uses it instead of /ready."""
    monkeypatch.setattr(db, "reachable", lambda: False)
    assert client.get("/health").status_code == 200


def test_ready_reports_the_database(client, monkeypatch):
    monkeypatch.setattr(db, "reachable", lambda: False)
    monkeypatch.setattr(app_module.cache, "reachable", lambda: True)
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.get_json()["database"] == "unreachable"


def test_ready_survives_a_cache_outage(client, monkeypatch):
    """Redis down is degraded, not unhealthy: reads fall through."""
    monkeypatch.setattr(db, "reachable", lambda: True)
    monkeypatch.setattr(app_module.cache, "reachable", lambda: False)
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.get_json()["status"] == "degraded"


def test_index_counts_only_open_tasks(client):
    body = client.get("/").data.decode()
    assert "Renew the domain" in body
    assert ">1<" in body.replace(" ", "").replace("\n", "")


def test_blank_title_is_ignored(client, monkeypatch):
    added = []
    monkeypatch.setattr(tasks, "add", lambda t, n: added.append(t))
    client.post("/tasks", data={"title": "   ", "notes": "x"})
    assert added == []


def test_api_returns_json(client):
    rows = client.get("/api/tasks").get_json()
    assert [r["id"] for r in rows] == [1, 2]
