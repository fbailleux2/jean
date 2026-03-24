"""Tests for Prometheus /metrics endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_aggregator_metrics():
    from jean.aggregator.api import app
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "# HELP" in resp.text


def test_validator_metrics():
    from jean.validator.api import app
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "# HELP" in resp.text


def test_validator_ui_root_redirect():
    from jean.validator.api import app
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code in (301, 302, 307, 308)
    assert "/ui" in resp.headers.get("location", "")


def test_validator_ui_returns_html():
    from jean.validator.api import app
    client = TestClient(app, follow_redirects=True)
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
