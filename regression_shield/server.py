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
from typing import Optional

from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator

logger = logging.getLogger("regression_shield.server")

# Base directory for the repository / workspace
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_START_TIME = time.time()
_LATEST_REPORT = {}

# Evaluation & Judge Runtime Configuration
_CONFIG = {
    "api_key": os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    "model": os.environ.get("REGSHIELD_MODEL", "minimax/minimax-m2.7:free"),
    "base_url": os.environ.get("REGSHIELD_BASE_URL", "https://openrouter.ai/api/v1"),
    "use_llm_judge": False,
}


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
                "active_model": _CONFIG.get("model"),
                "base_url": _CONFIG.get("base_url"),
                "llm_judge_configured": bool(_CONFIG.get("api_key")),
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

        # 1. Ingestion Endpoint for Any External Agent Execution Trace
        if path in ("/api/evaluate-trace", "/api/evaluate-trajectory", "/api/ingest"):
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                payload = json.loads(body)

                scenario = payload.get("scenario")
                raw_trace = payload.get("trace") or payload.get("trajectory") or payload.get("steps") or {}

                if isinstance(raw_trace, list):
                    raw_trace = {"steps": raw_trace, "final_response": payload.get("final_response", "")}

                if not scenario:
                    sc_id = payload.get("scenario_id", "CUSTOM_AGENT")
                    scenario = {
                        "scenario_id": sc_id,
                        "title": payload.get("title", f"Agent Trace: {sc_id}"),
                        "domain": payload.get("domain", "General / Autonomous Agent"),
                        "expected_tools": payload.get("expected_tools", []),
                        "expected_arguments": payload.get("expected_arguments", {}),
                        "expected_order": payload.get("expected_order", []),
                    }

                # Resolve parameters per request or fallback to server config
                req_api_key = payload.get("api_key") or _CONFIG.get("api_key")
                req_model = payload.get("model") or _CONFIG.get("model")
                req_base_url = payload.get("base_url") or _CONFIG.get("base_url")
                req_use_judge = payload.get("use_llm_judge", _CONFIG.get("use_llm_judge", False))
                eff_thresh = payload.get("min_trace_efficiency", payload.get("min_trajectory_efficiency", 0.70))

                evaluator = AgentTrajectoryEvaluator(
                    api_key=req_api_key,
                    model=req_model,
                    base_url=req_base_url,
                    use_llm_judge=req_use_judge,
                    min_tool_selection=payload.get("min_tool_selection", 0.85),
                    min_argument_correctness=payload.get("min_argument_correctness", 0.85),
                    min_order_accuracy=payload.get("min_order_accuracy", 1.00),
                    min_trace_efficiency=eff_thresh,
                )
                report = evaluator.evaluate_scenario(scenario, raw_trace)

                # Persist to latest_report for live dashboard
                report_data = _LATEST_REPORT or {}
                sc_list = report_data.setdefault("trace_baseline", [])
                sc_list = [c for c in sc_list if c.get("scenario_id") != report["scenario_id"]]
                sc_list.append(report)
                report_data["trace_baseline"] = sc_list
                report_data["trajectory_baseline"] = sc_list  # Backward-compatible alias
                report_data["timestamp"] = datetime.now(timezone.utc).isoformat()
                save_report_data(report_data)

                self._send_json_response({
                    "status": "success",
                    "scenario_id": report["scenario_id"],
                    "status_code": report["status"],
                    "composite_score": report["composite_score"],
                    "metrics": report["metrics"],
                    "failures": report["failures"],
                    "judge_audit": report.get("judge_audit"),
                    "details": report["details"],
                })
            except Exception as err:
                logger.exception("Error evaluating trajectory: %s", err)
                self._send_json_response({"status": "error", "error": str(err)}, 400)
            return

        self._send_json_response({"error": "Unknown API endpoint"}, 404)


def start_server(
    port: int = 8000,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    use_llm_judge: bool = False,
):
    global _CONFIG
    if api_key:
        _CONFIG["api_key"] = api_key
    if model:
        _CONFIG["model"] = model
    if base_url:
        _CONFIG["base_url"] = base_url
    if use_llm_judge:
        _CONFIG["use_llm_judge"] = use_llm_judge

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
    print(f"  * Ingestion API: POST http://localhost:{port}/api/evaluate-trace")
    if _CONFIG.get("model"):
        print(f"  * Model: {_CONFIG['model']} (Judge: {'Enabled' if _CONFIG.get('use_llm_judge') else 'Optional/Per-Request'})")
    print("=" * 65)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard server...")
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Start RegressionShield Dashboard Server")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--api-key", default=None, help="API key for LLM judge")
    parser.add_argument("--model", default=None, help="Default model identifier")
    parser.add_argument("--base-url", default=None, help="Base URL for OpenAI-compatible API")
    parser.add_argument("--llm-judge", action="store_true", help="Enable LLM judge by default")
    args = parser.parse_args()

    start_server(
        port=args.port,
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        use_llm_judge=args.llm_judge,
    )

