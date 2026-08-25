"""Lightweight local web server hosting the Executive Recovery Control Plane Dashboard.

Endpoints:
- GET /api/metrics           -> 7 Core KPI metrics summary
- GET /api/transactions      -> Paginated transaction list with filters
- GET /api/trace/<case_id>   -> Full cryptographic audit chain trace
- GET /                      -> Dashboard HTML/CSS/JS frontend
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sqlite3
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from agent import db as agent_db
from agent.dashboard import (
    compute_dashboard_metrics,
    get_transaction_detail,
    get_transaction_trace,
    get_transactions_summary,
)
from agent.demo_scenarios import run_demo_scenario
from agent.logger import get_logger

logger = get_logger("agent.dashboard.server")
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    conn: sqlite3.Connection

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/api/demo/trigger":
            self._handle_demo_trigger()
        elif path.startswith("/api/demo/"):
            scenario = path[len("/api/demo/"):]
            self._handle_demo_direct(scenario)
        else:
            self.send_error(404, "Endpoint not found")

    def _handle_demo_trigger(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            payload = json.loads(body)
            scenario = payload.get("scenario", "")
            result = run_demo_scenario(self.conn, scenario)
            self._send_json(result)
        except ValueError as e:
            self._send_json({"error": str(e)}, status=400)
        except Exception as e:
            logger.log_event("dashboard.demo.error", level="error", error=str(e), exc_info=True)
            self._send_json({"error": str(e)}, status=500)

    def _handle_demo_direct(self, scenario: str) -> None:
        try:
            result = run_demo_scenario(self.conn, scenario)
            self._send_json(result)
        except ValueError as e:
            self._send_json({"error": str(e)}, status=400)
        except Exception as e:
            logger.log_event("dashboard.demo.error", level="error", scenario=scenario, error=str(e), exc_info=True)
            self._send_json({"error": str(e)}, status=500)

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        if path == "/api/metrics":
            self._handle_metrics()
        elif path == "/api/transactions":
            self._handle_transactions(query)
        elif path.startswith("/api/transaction/"):
            case_id = path[len("/api/transaction/"):]
            self._handle_detail(case_id)
        elif path.startswith("/api/trace/"):
            case_id = path[len("/api/trace/"):]
            self._handle_trace(case_id)
        elif path == "/" or path == "/index.html":
            self._serve_file(DASHBOARD_DIR / "index.html", "text/html")
        elif path in ("/styles.css", "/app.js"):
            file_path = DASHBOARD_DIR / path.lstrip("/")
            mime_type = mimetypes.guess_type(str(file_path))[0] or "text/plain"
            self._serve_file(file_path, mime_type)
        else:
            # Fallback to default static file serving
            super().do_GET()

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists():
            self.send_error(404, f"File {file_path.name} not found")
            return
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def _send_json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _handle_metrics(self) -> None:
        try:
            metrics = compute_dashboard_metrics(self.conn)
            self._send_json(metrics)
        except Exception as e:
            logger.log_event("dashboard.metrics.error", level="error", error=str(e), exc_info=True)
            self._send_json({"error": str(e)}, status=500)

    def _handle_transactions(self, query: dict[str, list[str]]) -> None:
        try:
            limit = int(query.get("limit", [100])[0])
            offset = int(query.get("offset", [0])[0])
            search = query.get("search", [None])[0]
            cohort = query.get("cohort_filter", [None])[0]
            method = query.get("method_filter", [None])[0]
            state = query.get("state_filter", [None])[0]

            result = get_transactions_summary(
                self.conn,
                limit=limit,
                offset=offset,
                search=search,
                cohort_filter=cohort,
                method_filter=method,
                state_filter=state,
            )
            self._send_json(result)
        except Exception as e:
            logger.log_event("dashboard.transactions.error", level="error", error=str(e), exc_info=True)
            self._send_json({"error": str(e)}, status=500)

    def _handle_detail(self, case_id: str) -> None:
        try:
            detail = get_transaction_detail(self.conn, case_id)
            self._send_json(detail)
        except KeyError as e:
            self._send_json({"error": str(e)}, status=404)
        except Exception as e:
            logger.log_event("dashboard.detail.error", level="error", case_id=case_id, error=str(e), exc_info=True)
            self._send_json({"error": str(e)}, status=500)

    def _handle_trace(self, case_id: str) -> None:
        try:
            trace = get_transaction_trace(self.conn, case_id)
            self._send_json(trace)
        except KeyError as e:
            self._send_json({"error": str(e)}, status=404)
        except Exception as e:
            logger.log_event("dashboard.trace.error", level="error", case_id=case_id, error=str(e), exc_info=True)
            self._send_json({"error": str(e)}, status=500)


def populate_sample_dataset(conn: sqlite3.Connection, n: int = 50, seed: int = 777001) -> None:
    """Populate operational database with a realistic sample dataset for interactive dashboard inspection."""
    import random
    from datetime import datetime, timezone
    from agent.clock import VirtualClock
    from agent.diagnosis.stub import StubDiagnosis
    from agent.downtime import DowntimeStore
    from agent.executors.simulated import SimulatedExecutor
    from agent.pipeline import ingest, process_case
    from agent.policy.engine import load_rules
    from datagen.generator import generate_dataset

    logger.log_event("dashboard.dataset.generating", n=n, seed=seed)
    failures = generate_dataset(n=n, seed=seed)
    rules = load_rules()
    downtime = DowntimeStore(conn)
    clock = VirtualClock(start=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))

    # Hidden response model (40% base recovery probability for clean transient)
    def outcome_fn(verdict):
        return 0.75

    executor = SimulatedExecutor(conn, clock, outcome_fn, random.Random(seed))
    diagnosis = StubDiagnosis()

    for pf in failures:
        ingest(conn, pf, seed=seed, rules=rules, now=clock.now())
        process_case(
            conn,
            pf.case_id,
            clock=clock,
            rules=rules,
            downtime=downtime,
            diagnosis_port=diagnosis,
            executor=executor,
        )

    logger.log_event("dashboard.dataset.populated", count=n)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Recovery Control Plane Minimum Dashboard")
    parser.add_argument("--port", type=int, default=8000, help="HTTP server port (default: 8000)")
    parser.add_argument("--db", type=str, default=":memory:", help="SQLite database path (default: :memory:)")
    parser.add_argument("--n", type=int, default=100, help="Sample transactions to generate if empty (default: 100)")
    parser.add_argument("--seed", type=int, default=777001, help="Random seed for sample dataset")
    args = parser.parse_args()

    conn = agent_db.connect(args.db)
    DashboardRequestHandler.conn = conn

    # If empty database, populate sample dataset
    case_count = conn.execute("SELECT COUNT(*) AS c FROM cases").fetchone()["c"]
    if case_count == 0:
        print(f"Operational database is empty. Generating {args.n} sample transactions (seed={args.seed})...")
        populate_sample_dataset(conn, n=args.n, seed=args.seed)

    server_address = ("", args.port)
    httpd = HTTPServer(server_address, DashboardRequestHandler)
    print(f"\n=======================================================")
    print(f"  Executive Dashboard running at http://localhost:{args.port}")
    print(f"  - 7 Core Metrics: http://localhost:{args.port}/api/metrics")
    print(f"  - Transaction Ledger: http://localhost:{args.port}/api/transactions")
    print(f"=======================================================\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard server.")
        httpd.server_close()


if __name__ == "__main__":
    main()
