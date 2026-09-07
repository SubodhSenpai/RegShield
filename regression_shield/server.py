"""RegressionShield SDK Dynamic Dashboard Server.

Serves the visual observability dashboard and provides REST APIs for
zero-access trajectory ingestion from any external agent.
"""

import os
import sys
import json
import time
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime, timezone

from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator

logger = logging.getLogger("regression_shield.server")

# Base directory for the repository / workspace
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_START_TIME = time.time()
_LATEST_REPORT = {}


def save_report_data(data: dict):
    global _LATEST_REPORT
    _LATEST_REPORT = data
    reports_dir = os.path.join(WORKSPACE_DIR, "reports")
    try:
        os.makedirs(reports_dir, exist_ok=True)
        latest_path = os.path.join(reports_dir, "latest_report.json")
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as err:
        logger.warning("Could not persist report to disk: %s", err)


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler serving dashboard static files and evaluation ingestion REST APIs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WORKSPACE_DIR, **kwargs)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API: Server Health Status
        if path == "/api/status":
            uptime = round(time.time() - _START_TIME, 1)
            self._send_json_response({
                "status": "online",
                "uptime_seconds": uptime,
                "sdk_version": "0.2.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        # 2. API: Latest Evaluation Report
        if path == "/api/latest-report":
            if _LATEST_REPORT:
                self._send_json_response(_LATEST_REPORT)
                return

            report_path = os.path.join(WORKSPACE_DIR, "reports", "latest_report.json")
            if os.path.exists(report_path):
                try:
                    with open(report_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._send_json_response(data)
                    return
                except Exception as err:
                    self._send_json_response({"error": f"Failed to read report: {str(err)}"}, 500)
                    return

            self._send_json_response({"error": "No evaluation report available yet. Ingest an agent trace to begin."}, 404)
            return

        # 3. Serve Dashboard UI at root
        if path in ("/", "/dashboard", "/dashboard/"):
            index_path = os.path.join(WORKSPACE_DIR, "dashboard", "index.html")
            if os.path.exists(index_path):
                try:
                    with open(index_path, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Cache-Control", "no-cache")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception as err:
                    self.send_error(500, f"Error reading index.html: {err}")
                    return

        # Default static file serving
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. Ingestion Endpoint for Any External Agent Trace
        if path in ("/api/evaluate-trajectory", "/api/ingest"):
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                payload = json.loads(body)

                scenario = payload.get("scenario")
                trajectory = payload.get("trajectory") or payload.get("steps") or {}

                if isinstance(trajectory, list):
                    trajectory = {"steps": trajectory, "final_response": payload.get("final_response", "")}

                if not scenario:
                    sc_id = payload.get("scenario_id", "CUSTOM_AGENT")
                    scenario = {
                        "scenario_id": sc_id,
                        "title": payload.get("title", f"Agent Trajectory: {sc_id}"),
                        "domain": payload.get("domain", "General / Autonomous Agent"),
                        "expected_tools": payload.get("expected_tools", []),
                        "expected_arguments": payload.get("expected_arguments", {}),
                        "expected_order": payload.get("expected_order", []),
                    }

                evaluator = AgentTrajectoryEvaluator()
                report = evaluator.evaluate_scenario(scenario, trajectory)

                # Persist to latest_report for live dashboard
                report_data = _LATEST_REPORT or {}
                sc_list = report_data.setdefault("trajectory_baseline", [])
                sc_list = [c for c in sc_list if c.get("scenario_id") != report["scenario_id"]]
                sc_list.append(report)
                report_data["trajectory_baseline"] = sc_list
                report_data["timestamp"] = datetime.now(timezone.utc).isoformat()
                save_report_data(report_data)

                self._send_json_response({
                    "status": "success",
                    "scenario_id": report["scenario_id"],
                    "status_code": report["status"],
                    "composite_score": report["composite_score"],
                    "metrics": report["metrics"],
                    "failures": report["failures"],
                    "details": report["details"],
                })
            except Exception as err:
                logger.exception("Error evaluating trajectory: %s", err)
                self._send_json_response({"status": "error", "error": str(err)}, 400)
            return

        self._send_json_response({"error": "Unknown API endpoint"}, 404)


def start_server(port: int = 8000):
    server_address = ("", port)
    try:
        httpd = HTTPServer(server_address, DashboardHandler)
    except OSError as err:
        if "Address already in use" in str(err) or getattr(err, "errno", None) in (98, 10048):
            port = port + 1
            logger.info("Port busy, trying port %d...", port)
            httpd = HTTPServer(("", port), DashboardHandler)
        else:
            raise

    print("=" * 65)
    print("  RegressionShield Dynamic Dashboard Server is ONLINE")
    print(f"  * Dashboard URL: http://localhost:{port}")
    print(f"  * Ingestion API: POST http://localhost:{port}/api/evaluate-trajectory")
    print("=" * 65)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard server...")
        httpd.server_close()


if __name__ == "__main__":
    start_server()
