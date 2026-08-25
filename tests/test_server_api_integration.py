"""API & Server Integration Test Suite.

Tests actual HTTP requests against the dashboard web server.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import HTTPServer
import pytest

from agent import db as agent_db
from agent.models import (
    ErrorObj,
    Instrument,
    Method,
    PaymentFailure,
)
from agent.pipeline import ingest
from agent.policy.engine import load_rules
from scripts.serve_dashboard import DashboardRequestHandler, populate_sample_dataset


@pytest.fixture(scope="module")
def server():
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    populate_sample_dataset(conn, n=10, seed=42)

    DashboardRequestHandler.conn = conn
    httpd = HTTPServer(("127.0.0.1", 0), DashboardRequestHandler)
    port = httpd.server_address[1]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}"

    httpd.shutdown()
    httpd.server_close()


def test_http_get_index(server):
    url = f"{server}/"
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        content = response.read().decode("utf-8")
        assert "<title>Payment Recovery Control Plane | Executive Dashboard</title>" in content
        assert "Failure drills" in content or "Developer" in content


def test_http_get_static_assets(server):
    for asset in ("/styles.css", "/app.js"):
        url = f"{server}{asset}"
        with urllib.request.urlopen(url) as response:
            assert response.status == 200
            assert len(response.read()) > 0


def test_http_get_health_api(server):
    url = f"{server}/api/health"
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert data["audit_chain_valid"] is True
        assert "timestamp" in data


def test_http_get_metrics_api(server):
    url = f"{server}/api/metrics"
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert "revenue_at_risk_rupees" in data
        assert "recovered_value_rupees" in data
        assert "recovery_rate_pct" in data
        assert "actions_executed" in data
        assert "actions_blocked" in data
        assert "ai_confidence_pct" in data
        assert "failure_rate_pct" in data
        assert data["total_cases"] >= 10


def test_http_get_transactions_api(server):
    url = f"{server}/api/transactions?limit=5"
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert "transactions" in data
        assert len(data["transactions"]) <= 5
        assert "total" in data


def test_http_get_transaction_detail_and_trace(server):
    # First fetch list to get a valid case_id
    url_list = f"{server}/api/transactions?limit=1"
    with urllib.request.urlopen(url_list) as response:
        data = json.loads(response.read().decode("utf-8"))
        case_id = data["transactions"][0]["case_id"]

    # Test detail endpoint
    url_detail = f"{server}/api/transaction/{case_id}"
    with urllib.request.urlopen(url_detail) as response:
        assert response.status == 200
        detail = json.loads(response.read().decode("utf-8"))
        assert detail["case_id"] == case_id
        assert "event" in detail
        assert "context" in detail
        assert "ai_diagnosis" in detail
        assert "evidence" in detail
        assert "proposed_action" in detail
        assert "policy_result" in detail
        assert "execution" in detail
        assert "outcome" in detail
        assert "audit_trail" in detail

    # Test trace endpoint
    url_trace = f"{server}/api/trace/{case_id}"
    with urllib.request.urlopen(url_trace) as response:
        assert response.status == 200
        trace = json.loads(response.read().decode("utf-8"))
        assert trace["case_id"] == case_id
        assert trace["chain_valid"] is True


def test_http_post_demo_trigger(server):
    scenarios = ["duplicate_event", "invalid_ai_output", "policy_rejection", "execution_timeout"]

    for sc in scenarios:
        url = f"{server}/api/demo/trigger"
        req = urllib.request.Request(
            url,
            data=json.dumps({"scenario": sc}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as response:
            assert response.status == 200
            data = json.loads(response.read().decode("utf-8"))
            assert data["scenario"] == sc
            assert data["case_id"] is not None
            assert data["detail"]["audit_trail"]["chain_valid"] is True
