"""Local dashboard for RegShield: the dashboard page and a small JSON API.

    GET  /                    the dashboard
    GET  /api/status          server and LLM judge status
    GET  /api/latest-report   the report file (results and regression_results)
    POST /api/evaluate-trace  {"scenario": {...}, "trace": [...]} -> the evaluation report
    POST /api/reports         store a report made elsewhere (EvaluationReport.to_dict())
    POST /api/run-demo        evaluate the bundled sample scenarios

Security: listens on 127.0.0.1 by default and never serves files from disk. It
sends no CORS headers, accepts only JSON bodies, and rejects requests addressed
to other hostnames (DNS rebinding). The LLM judge always uses the server's own
key, model and endpoint.
"""

from __future__ import annotations

import errno
import ipaddress
import json
import logging
import os
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from regression_shield import __version__
from regression_shield.core.evaluator import JUDGE_ON_ERROR_CHOICES, AgentTraceEvaluator
from regression_shield.core.judge import LLMJudge
from regression_shield.models import DEFAULT_REPORT_PATH, load_report_file, save_reports

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
# Sample scenarios used by `regshield demo` and the dashboard's "Run demo" button
SAMPLE_SCENARIOS_FILE = os.path.join(os.path.dirname(__file__), "data", "sample_scenarios.json")
MAX_BODY_BYTES = 10 * 1024 * 1024
_THRESHOLD_FIELDS = ("min_tool_selection", "min_argument_correctness", "min_call_ordering",
                     "min_step_efficiency", "min_reasoning_faithfulness")


def _is_loopback(host: str) -> bool:
    """True for localhost and loopback IPs such as 127.0.0.1."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class DashboardSettings:
    """Where the dashboard keeps reports, and the LLM judge settings from ``regshield serve``
    flags (unset ones come from the environment, as in the SDK)."""

    workspace: str = field(default_factory=os.getcwd)  # reports go to <workspace>/reports/
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    use_llm_judge: bool = False
    judge_on_error: str = "fail"

    @property
    def report_path(self) -> str:
        return os.path.join(self.workspace, DEFAULT_REPORT_PATH)

    def judge(self) -> LLMJudge:
        return LLMJudge(api_key=self.api_key, model=self.model, base_url=self.base_url)

    def evaluator(self, use_llm_judge: bool = False, **thresholds: float) -> AgentTraceEvaluator:
        return AgentTraceEvaluator(use_llm_judge=use_llm_judge, api_key=self.api_key, model=self.model,
                                   base_url=self.base_url, judge_on_error=self.judge_on_error, **thresholds)


def run_demo(settings: DashboardSettings) -> dict[str, Any]:
    """Evaluate the bundled samples (passing and regressed traces) into the report file."""
    with open(SAMPLE_SCENARIOS_FILE, encoding="utf-8") as f:
        items = json.load(f)
    evaluator = settings.evaluator()
    results = [evaluator.evaluate(item["scenario"], item["trace"]) for item in items]
    regressions = [evaluator.evaluate(item["scenario"], item["regression_trace"])
                   for item in items if "regression_trace" in item]
    save_reports(results, settings.report_path, regression_reports=regressions, replace=True)
    return {"evaluated": len(results), "passed": sum(r.passed for r in results)}


class DashboardServer(ThreadingHTTPServer):
    """The dashboard's HTTP server. ``loopback_only`` is True when it listens on this machine only."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], settings: DashboardSettings | None = None):
        super().__init__(address, DashboardHandler)
        self.loopback_only = _is_loopback(address[0])
        self.settings = settings or DashboardSettings()
        self.started_at = time.time()


class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the dashboard page and the JSON API. Only the routes below exist."""

    server: DashboardServer

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Access log goes to the logger: visible with --verbose, server errors always
        message = f"{self.address_string()} {fmt % args}"
        (logger.warning if args and str(args[1]).startswith("5") else logger.debug)(message)

    def _reject_foreign_host(self) -> bool:
        """Block DNS rebinding: a local-only server answers only to local hostnames."""
        if not self.server.loopback_only:
            return False
        hostname = urlsplit("//" + self.headers.get("Host", "localhost")).hostname or ""
        if _is_loopback(hostname):
            return False
        self._send_json({"error": f"Host '{hostname}' is not allowed."}, 403)
        return True

    def do_GET(self) -> None:
        if self._reject_foreign_host():
            return
        path = urlsplit(self.path).path
        settings = self.server.settings
        if path == "/api/status":
            judge = settings.judge()
            self._send_json({
                "status": "online",
                "version": __version__,
                "uptime_seconds": round(time.time() - self.server.started_at, 1),
                "port": self.server.server_port,
                "llm_judge": {
                    "enabled": settings.use_llm_judge,
                    "has_api_key": bool(judge.api_key),
                    "model": judge.model,
                },
            })
        elif path == "/api/latest-report":
            if os.path.exists(settings.report_path):
                self._send_json(load_report_file(settings.report_path))
            else:
                self._send_json({"error": "No report yet. Run `regshield eval`, `regshield demo`, "
                                          "or POST to /api/evaluate-trace."}, 404)
        elif path in ("/", "/index.html"):
            try:
                with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
                    content = f.read()
            except OSError:
                self.send_error(500, "Dashboard page missing; reinstall regression-shield.")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _read_json(self) -> Any:
        # Browsers can send text/plain or form posts cross-site without asking;
        # requiring JSON means only same-origin pages and API clients get through.
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise _HTTPError(415, "Content-Type must be application/json")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise _HTTPError(413, f"Request body over {MAX_BODY_BYTES // (1024 * 1024)} MB")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self) -> None:
        if self._reject_foreign_host():
            return
        path = urlsplit(self.path).path
        handlers = {"/api/evaluate-trace": self._evaluate_trace, "/api/reports": self._store_report,
                    "/api/run-demo": lambda payload: run_demo(self.server.settings)}
        if path not in handlers:
            self._send_json({"error": "Not found"}, 404)
            return
        try:
            self._send_json(handlers[path](self._read_json()))
        except _HTTPError as err:
            self._send_json({"error": err.message}, err.status)
        except (ValueError, TypeError) as err:  # bad JSON, bad scenario or trace, judge misconfigured
            self._send_json({"error": str(err)}, 400)

    def _evaluate_trace(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or "scenario" not in payload or "trace" not in payload:
            raise _HTTPError(400, 'Send {"scenario": {...}, "trace": [...]}.')
        allowed = {"scenario", "trace", "use_llm_judge", *_THRESHOLD_FIELDS}
        unknown = set(payload) - allowed
        if unknown:
            # api_key / model / base_url are refused: the judge only uses the server's settings
            raise _HTTPError(400, f"Unknown field(s) {sorted(unknown)}. Allowed: {sorted(allowed)}. "
                                  "The LLM judge uses the server's own --api-key, --model and --base-url.")
        settings = self.server.settings
        use_judge = payload.get("use_llm_judge", settings.use_llm_judge) is True
        thresholds = {key: payload[key] for key in _THRESHOLD_FIELDS if key in payload}
        report = settings.evaluator(use_judge, **thresholds).evaluate(payload["scenario"], payload["trace"])
        self._save(report)
        return report.to_dict()

    def _store_report(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or not {"scenario_id", "status", "metrics"} <= set(payload):
            raise _HTTPError(400, "Send a report: EvaluationReport.to_dict().")
        self._save(payload)
        return {"saved": payload["scenario_id"]}

    def _save(self, report: Any) -> None:
        try:
            save_reports([report], self.server.settings.report_path)
        except OSError as err:
            logger.warning("Could not save the report: %s", err)


class _HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def create_server(host: str = "127.0.0.1", port: int = 8000,
                  settings: DashboardSettings | None = None) -> DashboardServer:
    """Bind the dashboard server without starting it (tries port + 1 once if busy)."""
    try:
        return DashboardServer((host, port), settings)
    except OSError as err:
        if err.errno not in (errno.EADDRINUSE, 10048):  # 10048: WSAEADDRINUSE on Windows
            raise
        logger.info("Port %d is busy, trying %d", port, port + 1)
        return DashboardServer((host, port + 1), settings)


def start_server(
    port: int = 8000,
    host: str = "127.0.0.1",
    open_browser: bool = False,
    use_llm_judge: bool = False,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    judge_on_error: str = "fail",
) -> None:
    """Run the dashboard until Ctrl+C.

    ``host`` 127.0.0.1 (default) accepts connections from this machine only;
    "0.0.0.0" exposes the dashboard to other machines, with no authentication.
    With ``use_llm_judge``, traces posted to the API can be judged by an LLM.
    """
    if judge_on_error not in JUDGE_ON_ERROR_CHOICES:
        raise ValueError(f"judge_on_error must be one of {JUDGE_ON_ERROR_CHOICES}, got {judge_on_error!r}")
    settings = DashboardSettings(api_key=api_key, model=model, base_url=base_url,
                                 use_llm_judge=use_llm_judge, judge_on_error=judge_on_error)
    if use_llm_judge and not settings.judge().api_key:
        raise ValueError("--llm-judge needs an API key: pass --api-key or set OPENROUTER_API_KEY / OPENAI_API_KEY.")

    httpd = create_server(host, port, settings)
    browse_host = "localhost" if httpd.loopback_only or host in ("", "0.0.0.0") else host
    url = f"http://{browse_host}:{httpd.server_port}"
    print(f"RegShield dashboard: {url}")
    print(f"Reports: {settings.report_path}")
    print(f"LLM judge: {'on, ' + settings.judge().model if use_llm_judge else 'off'}")
    if not httpd.loopback_only:
        print(f"Warning: listening on {host or 'all interfaces'}. Anyone who can reach this machine "
              "can use the dashboard and API; there is no authentication.")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
