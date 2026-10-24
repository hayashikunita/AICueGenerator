from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.persistence.db import SCHEMA_VERSION


def test_health_requires_token() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")
    assert resp.status_code == 401


def test_health_rejects_wrong_token() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/health", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_health_ok_with_token() -> None:
    with TestClient(app) as client:
        token = app.state.token
        resp = client.get("/api/v1/health", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["rekordbox"]["state"] == "not_implemented"
