"""The dashboard server: routes, and the protections around the local API."""

import http.client
import inspect
import json
import threading

import httpx
import pytest

from regression_shield import evaluate_trace, server

SCENARIO = {"scenario_id": "SRV_01", "expected_tools": ["deploy"]}
TRACE = [{"thought": "Deploying.", "action": {"name": "deploy", "args": {}}, "observation": "ok"}]
FAKE_SECRET = "sk-should-never-be-served"


class FakeJudgeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"choices": [{"message": {"content": '{"score": 0.9, "reasoning": "Grounded."}'}}]}


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    """A real server on a free local port, started in a folder holding secrets."""
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={FAKE_SECRET}\n")
    (tmp_path / "my_project").mkdir()
    (tmp_path / "my_project" / "agent.py").write_text("print('private code')\n")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    httpd = server.create_server("127.0.0.1", 0, server.DashboardSettings(workspace=str(tmp_path)))
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def request(httpd, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def post_json(httpd, path, payload, headers=None):
    return request(httpd, "POST", path, json.dumps(payload), {"Content-Type": "application/json", **(headers or {})})


def test_listens_on_localhost_by_default():
    httpd = server.create_server(port=0)
    try:
        assert httpd.server_address[0] == "127.0.0.1" and httpd.loopback_only
    finally:
        httpd.server_close()
    assert inspect.signature(server.start_server).parameters["host"].default == "127.0.0.1"


def test_serves_the_dashboard(dashboard):
    status, headers, body = request(dashboard, "GET", "/")
    assert status == 200 and headers["content-type"].startswith("text/html")
    assert b"<title>RegShield Dashboard</title>" in body


@pytest.mark.parametrize("path", ["/.env", "/my_project/", "/my_project/agent.py", "/reports/latest_report.json"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_never_serves_files_from_disk(dashboard, method, path):
    status, _, body = request(dashboard, method, path)
    assert status in (404, 501)
    assert FAKE_SECRET.encode() not in body and b"private code" not in body


def test_sends_no_cors_headers(dashboard):
    _, headers, _ = request(dashboard, "GET", "/api/status", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in headers
    status, headers, _ = request(dashboard, "OPTIONS", "/api/evaluate-trace", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert status != 200 and "access-control-allow-origin" not in headers


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data"])
def test_post_requires_json(dashboard, tmp_path, content_type):
    body = json.dumps({"scenario": SCENARIO, "trace": TRACE})
    status, _, _ = request(dashboard, "POST", "/api/evaluate-trace", body, {"Content-Type": content_type})
    assert status == 415
    assert not (tmp_path / "reports").exists()


def test_rejects_oversized_bodies(dashboard):
    headers = {"Content-Type": "application/json", "Content-Length": str(server.MAX_BODY_BYTES + 1)}
    conn = http.client.HTTPConnection("127.0.0.1", dashboard.server_port, timeout=10)
    conn.putrequest("POST", "/api/evaluate-trace")
    for key, value in headers.items():
        conn.putheader(key, value)
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()


def test_evaluates_a_trace_and_saves_it(dashboard, tmp_path):
    status, _, body = post_json(dashboard, "/api/evaluate-trace", {"scenario": SCENARIO, "trace": TRACE})
    assert status == 200
    assert json.loads(body)["status"] == "PASSED"
    saved = json.loads((tmp_path / "reports" / "latest_report.json").read_text())
    assert saved["results"][0]["scenario_id"] == "SRV_01"
    _, _, latest = request(dashboard, "GET", "/api/latest-report")
    assert json.loads(latest)["results"][0]["scenario_id"] == "SRV_01"


def test_response_includes_pattern_results(dashboard):
    payload = {"scenario": {"scenario_id": "HITL", "requires_approval": ["issue_refund"]},
               "trace": [{"action": {"type": "approval", "tool": "issue_refund", "approved": False}},
                         {"action": {"name": "issue_refund", "args": {}}, "observation": "REFUNDED"}]}
    result = json.loads(post_json(dashboard, "/api/evaluate-trace", payload)[2])
    assert result["status"] == "FAILED"
    assert result["patterns"]["human_approval"]["violations"] == ["Step 2: 'issue_refund' ran after its approval was denied"]


@pytest.mark.parametrize("payload, message", [
    ({"trace": TRACE}, 'Send {"scenario"'),
    ({"scenario": SCENARIO, "trace": TRACE, "api_key": "sk-attacker"}, "uses the server's own"),
    ({"scenario": SCENARIO, "trace": TRACE, "base_url": "http://attacker.example/v1"}, "uses the server's own"),
    ({"scenario": {**SCENARIO, "expected_tool": ["x"]}, "trace": TRACE}, "Unknown scenario field"),
])
def test_bad_payloads_get_a_clear_400(dashboard, payload, message):
    status, _, body = post_json(dashboard, "/api/evaluate-trace", payload)
    assert status == 400 and message in json.loads(body)["error"]


def test_judge_only_uses_the_servers_own_settings(dashboard, monkeypatch):
    dashboard.settings.api_key = "sk-server-key"
    dashboard.settings.base_url = "https://judge.example/v1"
    dashboard.settings.model = "server-model"
    calls = []

    def fake_post(self, url, **kwargs):
        calls.append((url, kwargs["headers"]["Authorization"], kwargs["json"]["model"]))
        return FakeJudgeResponse()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    status, _, _ = post_json(dashboard, "/api/evaluate-trace", {"scenario": SCENARIO, "trace": TRACE,
                                                                  "use_llm_judge": True})
    assert status == 200
    assert calls == [("https://judge.example/v1/chat/completions", "Bearer sk-server-key", "server-model")]


def test_judge_request_without_a_server_key_is_rejected(dashboard):
    status, _, body = post_json(dashboard, "/api/evaluate-trace", {"scenario": SCENARIO, "trace": TRACE,
                                                                     "use_llm_judge": True})
    assert status == 400 and "needs an API key" in json.loads(body)["error"]


@pytest.mark.parametrize("hostname, expected", [("evil.example", 403), ("localhost", 200), ("127.0.0.1", 200)])
def test_rejects_foreign_host_headers(dashboard, hostname, expected):
    host = f"{hostname}:{dashboard.server_port}"
    assert request(dashboard, "GET", "/api/status", headers={"Host": host})[0] == expected
    assert post_json(dashboard, "/api/evaluate-trace", {"scenario": SCENARIO, "trace": TRACE}, {"Host": host})[0] == expected


def test_exposed_server_accepts_any_host(dashboard):
    dashboard.loopback_only = False  # as with --host 0.0.0.0
    assert request(dashboard, "GET", "/api/status", headers={"Host": "192.168.1.8:8000"})[0] == 200


def test_sync_to_dashboard_stores_the_report_without_re_evaluating(dashboard, tmp_path):
    report = evaluate_trace({"scenario_id": "SYNC", "forbidden_tools": ["deploy"]}, TRACE)
    assert report.sync_to_dashboard(f"http://127.0.0.1:{dashboard.server_port}") is True
    saved = json.loads((tmp_path / "reports" / "latest_report.json").read_text())["results"][0]
    assert saved["scenario_id"] == "SYNC" and saved["status"] == "FAILED"  # the scenario's rules were kept


def test_run_demo(dashboard, tmp_path):
    status, _, body = post_json(dashboard, "/api/run-demo", {})
    assert status == 200 and json.loads(body) == {"evaluated": 10, "passed": 10}
    saved = json.loads((tmp_path / "reports" / "latest_report.json").read_text())
    assert len(saved["regression_results"]) == 10


def test_status_reports_version_and_judge(dashboard):
    status = json.loads(request(dashboard, "GET", "/api/status")[2])
    assert status["version"] == "0.4.0"
    assert status["llm_judge"]["enabled"] is False


def test_start_server_rejects_the_judge_without_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="needs an API key"):
        server.start_server(port=0, use_llm_judge=True)


def test_is_loopback():
    assert all(server._is_loopback(h) for h in ("localhost", "127.0.0.1", "127.0.0.2"))
    assert not any(server._is_loopback(h) for h in ("", "0.0.0.0", "192.168.1.8", "evil.example"))
