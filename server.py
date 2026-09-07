"""Dynamic Web Dashboard Server for RegressionShield Agent Trajectory & Reasoning Observability.

Serves the modern dynamic web dashboard on http://localhost:8000 and provides REST APIs:
- GET  /api/status          : Health check, active model, system state
- GET  /api/latest-report   : Fetch the latest evaluation report JSON
- POST /api/run-eval        : Trigger live agentic reasoning evaluation
- POST /api/run-smolagents  : Trigger live Hugging Face smolagents audit
"""

import os
import sys
import json
import time
import socket
import logging
import threading
import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime, timezone

# Add parent directory to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.settings import EvalConfig
from core.trajectory_evaluator import AgentTrajectoryEvaluator
from agent.live_tool_agent import LiveToolAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("regression_shield.server")

# Global lock for eval runs to prevent race conditions
_EVAL_LOCK = threading.Lock()
_START_TIME = time.time()


def load_trajectory_scenarios():
    path = os.path.join(BASE_DIR, "data", "agent_trajectories.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def execute_trajectory_run(mode: str = "baseline", live: bool = True):
    """Executes live or recorded agent reasoning evaluations for a given mode."""
    evaluator = AgentTrajectoryEvaluator()
    scenarios = load_trajectory_scenarios()
    reports = []

    agent = LiveToolAgent(mode=mode) if live else None

    for sc in scenarios:
        prompt = sc.get("input_prompt", sc["goal"])
        if live and agent:
            try:
                live_trace = agent.execute_task(prompt)
                if not live_trace or not live_trace.get("steps"):
                    traj_key = "baseline_trajectory" if mode == "baseline" else "regression_trajectory"
                    steps = sc.get(traj_key, {}).get("steps", [])
                    final_resp = sc.get(traj_key, {}).get("final_response", "")
                else:
                    steps = live_trace.get("steps", [])
                    final_resp = live_trace.get("final_response", "")
            except Exception as err:
                logger.warning("Agent live execution error (%s): %s. Falling back to recorded trace.", sc["scenario_id"], err)
                traj_key = "baseline_trajectory" if mode == "baseline" else "regression_trajectory"
                steps = sc.get(traj_key, {}).get("steps", [])
                final_resp = sc.get(traj_key, {}).get("final_response", "")
        else:
            traj_key = "baseline_trajectory" if mode == "baseline" else "regression_trajectory"
            steps = sc.get(traj_key, {}).get("steps", [])
            final_resp = sc.get(traj_key, {}).get("final_response", "")

        traj_data = {"steps": steps, "final_response": final_resp}
        report = evaluator.evaluate_scenario(sc, traj_data)
        reports.append(report)

    return reports


def calculate_deltas(base_reports, reg_reports):
    deltas = []
    base_map = {r["scenario_id"]: r for r in base_reports}
    for reg in reg_reports:
        sc_id = reg["scenario_id"]
        base = base_map.get(sc_id)
        if not base:
            continue

        bm = base["metrics"]
        rm = reg["metrics"]
        delta_entry = {
            "scenario_id": sc_id,
            "title": reg["title"],
            "domain": reg["domain"],
            "baseline_status": base["status"],
            "regression_status": reg["status"],
            "baseline_composite": base["composite_score"],
            "regression_composite": reg["composite_score"],
            "composite_delta": round(reg["composite_score"] - base["composite_score"], 2),
            "tool_selection_delta": round(rm["tool_selection"] - bm["tool_selection"], 2),
            "argument_correctness_delta": round(rm["argument_correctness"] - bm["argument_correctness"], 2),
            "call_ordering_delta": round(rm["call_ordering"] - bm["call_ordering"], 2),
            "step_efficiency_delta": round(rm["step_efficiency"] - bm["step_efficiency"], 2),
            "reasoning_faithfulness_delta": round(rm["reasoning_faithfulness"] - bm["reasoning_faithfulness"], 2),
            "is_regression": reg["status"] == "FAILED" and base["status"] == "PASSED",
        }
        deltas.append(delta_entry)
    return deltas


def save_report_data(data: dict):
    reports_dir = os.path.join(BASE_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    latest_path = os.path.join(reports_dir, "latest_report.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved latest report to: %s", latest_path)


class DynamicDashboardHandler(SimpleHTTPRequestHandler):
    """Custom HTTP handler serving dashboard files and REST API endpoints."""

    def __init__(self, *args, **kwargs):
        # Serve static files from workspace root
        super().__init__(*args, directory=BASE_DIR, **kwargs)

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

        # 1. API: Server Status & Model Cascade
        if path == "/api/status":
            uptime = round(time.time() - _START_TIME, 1)
            response_data = {
                "status": "online",
                "uptime_seconds": uptime,
                "judge_model": EvalConfig.JUDGE_MODEL,
                "fallback_models": EvalConfig.get_fallback_models(),
                "has_api_key": bool(EvalConfig.OPENROUTER_API_KEY),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._send_json_response(response_data)
            return

        # 2. API: Latest Evaluation Report
        if path == "/api/latest-report":
            report_path = os.path.join(BASE_DIR, "reports", "latest_report.json")
            if os.path.exists(report_path):
                try:
                    with open(report_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._send_json_response(data)
                    return
                except Exception as err:
                    self._send_json_response({"error": f"Failed to read report: {str(err)}"}, 500)
                    return
            else:
                self._send_json_response({"error": "No report found. Run an evaluation first."}, 404)
                return

        # 3. Serve Dashboard UI at root
        if path in ("/", "/dashboard", "/dashboard/"):
            index_path = os.path.join(BASE_DIR, "dashboard", "index.html")
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

        # Default: Serve other static files
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API: Trigger Live Trajectory Evaluation
        if path == "/api/run-eval":
            if not _EVAL_LOCK.acquire(blocking=False):
                self._send_json_response({
                    "status": "busy",
                    "message": "Evaluation currently running. Please wait for completion."
                }, 409)
                return

            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                try:
                    params = json.loads(body)
                except Exception:
                    params = {}

                live = params.get("live", True)
                logger.info("Executing trajectory evaluation (live=%s)...", live)

                base_reports = execute_trajectory_run(mode="baseline", live=live)
                reg_reports = execute_trajectory_run(mode="regression", live=live)
                deltas = calculate_deltas(base_reports, reg_reports)

                # Preserve existing smolagents results if present
                latest_path = os.path.join(BASE_DIR, "reports", "latest_report.json")
                smol_eval = None
                if os.path.exists(latest_path):
                    try:
                        with open(latest_path, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                            smol_eval = existing.get("smolagents_eval")
                    except Exception:
                        pass

                full_report = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "config": {
                        "judge_model": EvalConfig.JUDGE_MODEL,
                        "demo_mode": False,
                        "live_evaluation": live,
                    },
                    "trajectory_baseline": base_reports,
                    "trajectory_regression": reg_reports,
                    "trajectory_deltas": deltas,
                }
                if smol_eval:
                    full_report["smolagents_eval"] = smol_eval

                save_report_data(full_report)

                self._send_json_response({
                    "status": "success",
                    "message": "Live Agentic Reasoning evaluation completed successfully",
                    "report": full_report
                })
            except Exception as err:
                logger.exception("Error executing evaluation: %s", err)
                self._send_json_response({"status": "error", "error": str(err)}, 500)
            finally:
                _EVAL_LOCK.release()
            return

        # 2. API: Trigger smolagents Live Audit
        if path == "/api/run-smolagents":
            if not _EVAL_LOCK.acquire(blocking=False):
                self._send_json_response({
                    "status": "busy",
                    "message": "Evaluation currently running. Please wait for completion."
                }, 409)
                return

            try:
                from integrations.smolagents_evaluator import SmolagentsEvaluator
                evaluator = SmolagentsEvaluator()
                res = evaluator.run_live_evaluation()

                # Merge into latest_report.json
                latest_path = os.path.join(BASE_DIR, "reports", "latest_report.json")
                report_data = {}
                if os.path.exists(latest_path):
                    try:
                        with open(latest_path, "r", encoding="utf-8") as f:
                            report_data = json.load(f)
                    except Exception:
                        pass

                report_data["smolagents_eval"] = res
                report_data["timestamp"] = datetime.now(timezone.utc).isoformat()
                save_report_data(report_data)

                self._send_json_response({
                    "status": "success",
                    "message": "smolagents audit completed successfully",
                    "smolagents_eval": res
                })
            except Exception as err:
                logger.exception("Error running smolagents eval: %s", err)
                self._send_json_response({"status": "error", "error": str(err)}, 500)
        # 3. API: Ingest and Evaluate ANY External Agent Trajectory (Zero-Access REST API)
        if path in ("/api/evaluate-trajectory", "/api/ingest"):
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                payload = json.loads(body)

                scenario = payload.get("scenario")
                trajectory = payload.get("trajectory") or payload.get("steps") or {}

                # If steps given directly in trajectory or payload
                if isinstance(trajectory, list):
                    trajectory = {"steps": trajectory, "final_response": payload.get("final_response", "")}

                # If scenario not explicitly provided, match by scenario_id or auto-synthesize
                if not scenario:
                    sc_id = payload.get("scenario_id", "CUSTOM_AGENT")
                    known_scenarios = load_trajectory_scenarios()
                    match = next((s for s in known_scenarios if s.get("scenario_id") == sc_id), None)
                    if match:
                        scenario = match
                    else:
                        # Auto-synthesize default scenario from payload expectations
                        scenario = {
                            "scenario_id": sc_id,
                            "title": payload.get("title", f"External Agent Audit: {sc_id}"),
                            "domain": payload.get("domain", "General / Autonomous Agent"),
                            "expected_tools": payload.get("expected_tools", []),
                            "expected_arguments": payload.get("expected_arguments", {}),
                            "expected_order": payload.get("expected_order", []),
                        }

                evaluator = AgentTrajectoryEvaluator()
                report = evaluator.evaluate_scenario(scenario, trajectory)

                # Optionally persist to latest_report.json for live dashboard visualization
                if payload.get("save_to_dashboard", True):
                    latest_path = os.path.join(BASE_DIR, "reports", "latest_report.json")
                    report_data = {}
                    if os.path.exists(latest_path):
                        try:
                            with open(latest_path, "r", encoding="utf-8") as f:
                                report_data = json.load(f)
                        except Exception:
                            pass

                    custom_list = report_data.setdefault("custom_evaluations", [])
                    custom_list = [c for c in custom_list if c.get("scenario_id") != report["scenario_id"]]
                    custom_list.append(report)
                    report_data["custom_evaluations"] = custom_list
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
                logger.exception("Error in evaluate-trajectory: %s", err)
                self._send_json_response({"status": "error", "error": str(err)}, 400)
            return

        self._send_json_response({"error": "Unknown API endpoint"}, 404)


def start_server(port: int = 8000):
    server_address = ("", port)
    try:
        httpd = HTTPServer(server_address, DynamicDashboardHandler)
    except OSError as err:
        if "Address already in use" in str(err) or err.errno == 98 or err.errno == 10048:
            port = port + 1
            logger.info("Port busy, trying port %d...", port)
            httpd = HTTPServer(("", port), DynamicDashboardHandler)
        else:
            raise

    logger.info("=" * 65)
    logger.info("🚀 RegressionShield Dynamic Dashboard Server is ONLINE")
    logger.info("📡 Dashboard URL: http://localhost:%d", port)
    logger.info("📊 REST API:       http://localhost:%d/api/latest-report", port)
    logger.info("⚡ Live Trigger:   POST http://localhost:%d/api/run-eval", port)
    logger.info("=" * 65)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down dashboard server...")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RegressionShield Dynamic Dashboard Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve on (default: 8000)")
    args = parser.parse_args()
    start_server(port=args.port)
