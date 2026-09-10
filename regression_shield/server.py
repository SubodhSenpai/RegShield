"""RegressionShield SDK Dynamic Dashboard Server.

Serves the visual observability dashboard and provides REST APIs for
zero-access trajectory ingestion from any external agent.

The dashboard HTML is bundled inside the package at:
    regression_shield/static/index.html

This means `regshield serve` works from any directory after `pip install regression-shield`
— no need to clone the repo.
"""

import os
import sys
import json
import time
import logging
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer
except ImportError:
    from http.server import HTTPServer as ThreadingHTTPServer
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Optional

from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator

logger = logging.getLogger("regression_shield.server")

# ── Path resolution ──────────────────────────────────────────────────────────
# STATIC_DIR: the bundled dashboard HTML (inside the package, works after pip install)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# WORKSPACE_DIR: where reports are written — always the user's current working directory
# so `reports/latest_report.json` is created where they run `regshield serve`
WORKSPACE_DIR = os.getcwd()

_START_TIME = time.time()
_LATEST_REPORT: dict = {}

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
    """HTTP handler serving the bundled dashboard UI and evaluation REST APIs."""

    def __init__(self, *args, **kwargs):
        # Serve static files from the user's working directory (for reports/ fallback)
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
        self.send_header("Connection", "close")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Suppress noisy access logs; only log errors
        if args and len(args) >= 2 and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ── 1. API: Server Health Status ──────────────────────────────────────
        if path == "/api/status":
            uptime = round(time.time() - _START_TIME, 1)
            self._send_json_response({
                "status": "online",
                "uptime_seconds": uptime,
                "sdk_version": "0.3.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "judge_model": _CONFIG.get("model"),
                "active_model": _CONFIG.get("model"),
                "base_url": _CONFIG.get("base_url"),
                "llm_judge_configured": bool(_CONFIG.get("api_key")),
                "port": self.server.server_port,
            })
            return

        # ── 2. API: Latest Evaluation Report (Disk-first for fresh SDK runs) ───
        if path == "/api/latest-report":
            report_path = os.path.join(WORKSPACE_DIR, "reports", "latest_report.json")
            if os.path.exists(report_path):
                try:
                    with open(report_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    global _LATEST_REPORT
                    _LATEST_REPORT = data
                    self._send_json_response(data)
                    return
                except Exception as err:
                    logger.warning("Failed to read report from disk: %s", err)

            if _LATEST_REPORT:
                self._send_json_response(_LATEST_REPORT)
                return

            self._send_json_response(
                {"error": "No evaluation report available yet. Ingest an agent trace to begin."},
                404,
            )
            return

        # ── 3. API: Trigger Live Evaluation ───────────────────────────────────
        if path == "/api/run-eval":
            self._send_json_response({"message": "Use POST /api/run-eval or POST /api/evaluate-trace."}, 405)
            return

        # ── 4. Serve bundled Dashboard HTML at root & /dashboard ─────────────
        if path in ("/", "/dashboard", "/dashboard/"):
            index_path = os.path.join(STATIC_DIR, "index.html")
            if not os.path.exists(index_path):
                alt_path = os.path.join(WORKSPACE_DIR, "dashboard", "index.html")
                if os.path.exists(alt_path):
                    index_path = alt_path
            if os.path.exists(index_path):
                try:
                    with open(index_path, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception as err:
                    self.send_error(500, f"Error reading bundled dashboard: {err}")
                    return
            else:
                self.send_error(
                    500,
                    "Dashboard HTML not found. Re-install the package: pip install --upgrade regression-shield",
                )
                return

        # ── 5. Default: serve files from the user's working directory ─────────
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ── Ingestion Endpoint: Evaluate any external agent execution trace ───
        if path in ("/api/evaluate-trace", "/api/evaluate-trajectory", "/api/ingest", "/api/run-eval"):
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                payload = json.loads(body)

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

                # Special case: "Run Live Trace Eval" clicked in dashboard UI without explicit payload
                has_custom_trace = bool(payload.get("trace") or payload.get("trajectory") or payload.get("steps"))
                if path == "/api/run-eval" and (payload.get("live") or not has_custom_trace):
                    sample_file = os.path.join(WORKSPACE_DIR, "examples", "sample_scenarios.json")
                    if not os.path.exists(sample_file):
                        sample_file = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_scenarios.json")

                    if os.path.exists(sample_file):
                        with open(sample_file, "r", encoding="utf-8") as f:
                            samples = json.load(f)

                        b_reports = []
                        r_reports = []
                        for sc in samples:
                            b_trace = sc.get("baseline_trace") or sc.get("baseline_trajectory") or sc.get("trace") or []
                            r_trace = sc.get("regression_trace") or sc.get("regression_trajectory") or []
                            b_rep = evaluator.evaluate_scenario(sc, b_trace)
                            b_reports.append(b_rep)
                            if r_trace:
                                r_rep = evaluator.evaluate_scenario(sc, r_trace)
                                r_reports.append(r_rep)

                        report_data = {
                            "trace_baseline": b_reports,
                            "trajectory_baseline": b_reports,
                            "trace_regression": r_reports,
                            "trajectory_regression": r_reports,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        save_report_data(report_data)
                        self._send_json_response({
                            "status": "success",
                            "message": f"Evaluated {len(b_reports)} scenarios with baseline & regression traces!",
                            "count": len(b_reports),
                        })
                        return

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

                report = evaluator.evaluate_scenario(scenario, raw_trace)

                # Merge into the live report store
                report_data = dict(_LATEST_REPORT) if _LATEST_REPORT else {}
                sc_list = report_data.get("trace_baseline", [])
                sc_list = [c for c in sc_list if c.get("scenario_id") != report["scenario_id"]]
                sc_list.append(report)
                report_data["trace_baseline"] = sc_list
                report_data["trajectory_baseline"] = sc_list  # backward-compat alias
                report_data["timestamp"] = datetime.now(timezone.utc).isoformat()
                save_report_data(report_data)

                self._send_json_response({
                    "status": "success",
                    "message": f"Trace evaluated — {report['status']} (score: {report['composite_score']:.2f})",
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

        # ── smolagents audit stub (live audit requires local Python process) ──
        if path == "/api/run-smolagents":
            self._send_json_response({
                "status": "error",
                "error": "smolagents live audit requires a local Python process. "
                         "Use the Python SDK: from regression_shield.adapters.smolagents import evaluate_smolagent",
            }, 400)
            return

        self._send_json_response({"error": "Unknown API endpoint"}, 404)


def start_server(
    port: int = 8000,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    use_llm_judge: bool = False,
    open_browser: bool = False,
):
    """Start the RegressionShield dashboard server.

    Args:
        port: TCP port to bind (default 8000; auto-increments if busy).
        api_key: LLM judge API key.
        model: LLM model identifier for judge.
        base_url: OpenAI-compatible API base URL.
        use_llm_judge: Whether to enable LLM judge by default.
        open_browser: If True, automatically open the dashboard in the default browser.
    """
    global _CONFIG, WORKSPACE_DIR
    WORKSPACE_DIR = os.getcwd()  # snapshot cwd at server start

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
        httpd = ThreadingHTTPServer(server_address, DashboardHandler)
        httpd.daemon_threads = True
    except OSError as err:
        if "Address already in use" in str(err) or getattr(err, "errno", None) in (98, 10048):
            port = port + 1
            logger.info("Port busy, trying port %d...", port)
            httpd = ThreadingHTTPServer(("", port), DashboardHandler)
            httpd.daemon_threads = True
        else:
            raise

    url = f"http://localhost:{port}"

    print()
    print("-" * 65)
    print("  [*] RegressionShield Dashboard Server  --  ONLINE")
    print("-" * 65)
    print(f"  Dashboard  -->  {url}")
    print(f"  Ingest API -->  POST {url}/api/evaluate-trace")
    print(f"  Status API -->  GET  {url}/api/status")
    if _CONFIG.get("model"):
        judge_status = "Enabled" if _CONFIG.get("use_llm_judge") else "Optional (pass use_llm_judge=True)"
        print(f"  Judge      -->  {_CONFIG['model']}  ({judge_status})")
    print(f"  Reports    -->  {os.path.join(WORKSPACE_DIR, 'reports', 'latest_report.json')}")
    print("-" * 65)
    print("  Press Ctrl+C to stop the server.")
    print()

    if open_browser:
        # Slight delay so the server socket is ready before the browser hits it
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        print(f"  Opening browser --> {url}")
        print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down dashboard server...")
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Start RegressionShield Dashboard Server")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--api-key", default=None, help="API key for LLM judge")
    parser.add_argument("--model", default=None, help="Default model identifier")
    parser.add_argument("--base-url", default=None, help="Base URL for OpenAI-compatible API")
    parser.add_argument("--llm-judge", action="store_true", help="Enable LLM judge by default")
    parser.add_argument("--open", "-o", action="store_true", dest="open_browser",
                        help="Auto-open the dashboard in your browser")
    args = parser.parse_args()

    start_server(
        port=args.port,
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        use_llm_judge=args.llm_judge,
        open_browser=args.open_browser,
    )
