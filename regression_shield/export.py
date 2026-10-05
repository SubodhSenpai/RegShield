"""Send runs to a monitoring service while agents run.

    import regression_shield as rs
    rs.export_traces(rs.OpenTelemetryExporter(endpoint="http://localhost:4318"),
                     sample_rate=0.1, max_runs_per_minute=60)

From then on every recorder (``TraceRecorder``, the LangChain handler,
``instrument_smolagents`` and SDK calls captured by ``instrument()``) streams
each run as events: ``run_start``; each tool call, model call and pattern event
as it's recorded; and ``run_end`` with the run's status, tokens and cost.

Exporters: ``OpenTelemetryExporter`` (spans with the OpenTelemetry GenAI
attributes, for Grafana, Jaeger, Honeycomb, Datadog, Langfuse, Phoenix...),
``JSONLExporter`` (a file, for log shippers or later ``regshield eval``) and
``HTTPExporter`` (batches of JSON events to any URL). Subclass ``Exporter`` for
anything else.

Sampling: ``sample_rate`` is the share of runs exported. With ``keep_errors``
(the default) a run that wasn't sampled is held back and exported anyway as
soon as a tool fails, an action is blocked or a guard warns, so you see every
problem but only a sample of healthy runs. ``max_runs_per_minute`` caps how
many runs are exported; ``max_events_per_run`` caps each run's events.

Prompts, arguments, tool results and answers stay out of exports unless an
exporter has ``capture_content=True``.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import random
import threading
import time
import uuid
from collections import Counter, deque
from typing import Any

from regression_shield.config import load_config
from regression_shield.core.cost import merge_pricing, price_for
from regression_shield.core.faithfulness import is_error_observation
from regression_shield.core.patterns import action_of, event_type

logger = logging.getLogger(__name__)

_MAX_TEXT = 4096  # longest text attribute sent to OpenTelemetry


def _now() -> float:
    return time.time()


class Exporter:
    """Receives run events as they happen. Override ``export``; ``flush`` and
    ``shutdown`` send anything buffered. Exceptions are logged, never raised to the agent."""

    capture_content = False

    def export(self, event: dict[str, Any]) -> None:
        raise NotImplementedError

    def flush(self, timeout: float = 5.0) -> None:
        """Send buffered events now."""

    def shutdown(self, timeout: float = 5.0) -> None:
        """Flush and release resources. Called by ``stop_exporting`` and at exit."""
        self.flush(timeout)

    def visible(self, event: dict[str, Any]) -> dict[str, Any]:
        """The event without its ``content`` unless this exporter captures content."""
        if self.capture_content or "content" not in event:
            return event
        return {key: value for key, value in event.items() if key != "content"}


# -- events ---------------------------------------------------------------------------

def step_event(run_id: str, step: dict[str, Any], start: float, end: float) -> dict[str, Any]:
    """The export event for a recorded step (a tool call or a pattern event)."""
    kind = event_type(step)
    action = action_of(step)
    event: dict[str, Any] = {"event": kind, "run_id": run_id, "step": step.get("step_index"), "ts": end}
    for key in ("agent", "node", "parallel_group"):
        if step.get(key) is not None:
            event[key] = step[key]
    content: dict[str, Any] = {}
    if kind == "tool_call":
        name = str(action.get("name") or "tool")
        blocked = step.get("blocked")
        if blocked:
            status = "blocked"
        elif is_error_observation(step.get("observation"), name):
            status = "error"
        else:
            status = "ok"
        event.update(tool=name, status=status, ts_start=start, duration_ms=round(max(0.0, end - start) * 1000, 3))
        if isinstance(blocked, dict):
            event["blocked_rule"] = blocked.get("rule")
        warning = step.get("guard_warning")
        if isinstance(warning, dict):
            event["warning_rule"] = warning.get("rule")
            content["warning"] = warning.get("reason")
        if step.get("cost_usd") is not None:
            event["cost_usd"] = step["cost_usd"]
        content.update(args=action.get("args") or action.get("arguments") or {},
                       observation=step.get("observation"), thought=step.get("thought"))
    elif kind in ("handoff", "route"):
        event["to"] = action.get("to")
    elif kind == "approval":
        event.update(tool=action.get("tool"), approved=action.get("approved", True), by=action.get("by"))
    elif kind == "node":
        event["name"] = action.get("name")
    elif kind == "plan":
        content["steps"] = action.get("steps")
    elif kind == "draft":
        content["text"] = action.get("content")
    elif kind == "critique":
        event["approved"] = action.get("approved")
        content["feedback"] = action.get("feedback")
    content = {key: value for key, value in content.items() if value not in (None, "")}
    if content:
        event["content"] = content
    return event


def llm_event(run_id: str, call: dict[str, Any], start: float, end: float,
              pricing: dict[str, Any] | None = None) -> dict[str, Any]:
    """The export event for a recorded model call, with its cost when it can be priced."""
    event: dict[str, Any] = {"event": "llm_call", "run_id": run_id, "ts": end, "ts_start": start,
                             "duration_ms": round(max(0.0, end - start) * 1000, 3), "model": call.get("model"),
                             "input_tokens": call.get("input_tokens", 0), "output_tokens": call.get("output_tokens", 0)}
    for key in ("cached_input_tokens", "cache_write_tokens", "agent"):
        if call.get(key):
            event[key] = call[key]
    if call.get("cost_usd") is not None:
        event["cost_usd"] = call["cost_usd"]
    else:
        price = price_for(str(call.get("model") or ""), pricing)
        if price is not None:
            event["cost_usd"] = round(price.cost(call.get("input_tokens", 0), call.get("output_tokens", 0),
                                                 call.get("cached_input_tokens", 0), call.get("cache_write_tokens", 0)), 8)
    return event


def _alerts(event: dict[str, Any]) -> bool:
    """Events that make a held-back run worth exporting."""
    return event.get("status") in ("error", "blocked") or "warning_rule" in event


# -- the pipeline -----------------------------------------------------------------------

class RunExport:
    """One run's events on their way to the exporters (sampled, held back or dropped)."""

    def __init__(self, pipeline: ExportPipeline, name: str | None, agent: str | None, attributes: dict[str, Any]):
        self.pipeline = pipeline
        self.run_id = uuid.uuid4().hex
        self.started = _now()
        self._lock = threading.Lock()
        self._buffer: list[dict[str, Any]] = []
        self._sent = 0
        self.truncated = False
        if random.random() < pipeline.sample_rate:
            self.mode = "stream" if pipeline._admit_run() else "drop"
        else:
            self.mode = "hold" if pipeline.keep_errors else "drop"
            if self.mode == "drop":
                pipeline.stats["runs_sampled_out"] += 1
        start: dict[str, Any] = {"event": "run_start", "run_id": self.run_id, "ts": self.started}
        if name:
            start["name"] = name
        if agent:
            start["agent"] = agent
        if attributes:
            start["attributes"] = attributes
        self.emit(start)

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            if self.mode == "hold":
                self._buffer.append(event)
                if _alerts(event):
                    self._release()
                return
            if self.mode == "stream":
                self._send(event)

    def _release(self) -> None:
        """A held-back run turned out to matter: export what it has so far, then stream."""
        if self.pipeline._admit_run():
            self.mode = "stream"
            self.pipeline.stats["runs_kept_for_errors"] += 1
            for event in self._buffer:
                self._send(event)
        else:
            self.mode = "drop"
        self._buffer = []

    def _send(self, event: dict[str, Any]) -> None:
        limit = self.pipeline.max_events_per_run
        if limit is not None and self._sent >= limit and event["event"] != "run_end":
            self.truncated = True
            self.pipeline.stats["events_dropped"] += 1
            return
        self._sent += 1
        self.pipeline._dispatch(event)

    def end(self, summary: dict[str, Any]) -> None:
        event = {"event": "run_end", "run_id": self.run_id, "ts": _now(), **summary}
        event["duration_ms"] = round((event["ts"] - self.started) * 1000, 3)
        with self._lock:
            if self.mode == "hold":
                if summary.get("status") != "ok":
                    self._release()
                else:
                    self.mode = "drop"
                    self._buffer = []
                    self.pipeline.stats["runs_sampled_out"] += 1
            if self.mode == "stream":
                event["truncated"] = self.truncated
                self._send(event)
                self.pipeline.stats["runs_exported"] += 1
            self.mode = "done"


class ExportPipeline:
    """Exporters plus sampling and rate limits. Made by ``export_traces``."""

    def __init__(self, exporters: list[Exporter], *, sample_rate: float = 1.0, keep_errors: bool = True,
                 max_runs_per_minute: int | None = None, max_events_per_run: int | None = None,
                 pricing: dict[str, Any] | None = None):
        if not exporters:
            raise ValueError("export_traces needs at least one exporter")
        for exporter in exporters:
            if not isinstance(exporter, Exporter):
                raise TypeError(f"{exporter!r} is not an Exporter (subclass regression_shield.Exporter)")
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, float)) or not 0 <= sample_rate <= 1:
            raise ValueError(f"sample_rate must be a number from 0 to 1, got {sample_rate!r}")
        for name, value in (("max_runs_per_minute", max_runs_per_minute), ("max_events_per_run", max_events_per_run)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a whole number >= 0, got {value!r}")
        self.exporters = list(exporters)
        self.sample_rate = float(sample_rate)
        self.keep_errors = keep_errors
        self.max_runs_per_minute = max_runs_per_minute
        self.max_events_per_run = max_events_per_run
        self.pricing = merge_pricing(load_config().get("pricing"), pricing)
        self.stats: Counter = Counter()
        self._lock = threading.Lock()
        self._run_times: deque[float] = deque()
        self._errors_logged = 0

    def begin(self, name: str | None = None, agent: str | None = None, **attributes: Any) -> RunExport:
        self.stats["runs_started"] += 1
        return RunExport(self, name, agent, attributes)

    def _admit_run(self) -> bool:
        """Count a run against max_runs_per_minute; False when the limit is reached."""
        if self.max_runs_per_minute is None:
            return True
        now = time.monotonic()
        with self._lock:
            while self._run_times and self._run_times[0] <= now - 60:
                self._run_times.popleft()
            if len(self._run_times) >= self.max_runs_per_minute:
                self.stats["runs_rate_limited"] += 1
                return False
            self._run_times.append(now)
            return True

    def _dispatch(self, event: dict[str, Any]) -> None:
        self.stats["events_exported"] += 1
        for exporter in self.exporters:
            try:
                exporter.export(event)
            except Exception as err:  # an exporter must never break the agent
                self.stats["export_errors"] += 1
                if self._errors_logged < 10:
                    self._errors_logged += 1
                    logger.warning("%s failed to export an event: %s", type(exporter).__name__, err)

    def flush(self, timeout: float = 5.0) -> None:
        for exporter in self.exporters:
            try:
                exporter.flush(timeout)
            except Exception as err:
                logger.warning("%s failed to flush: %s", type(exporter).__name__, err)

    def shutdown(self, timeout: float = 5.0) -> None:
        for exporter in self.exporters:
            try:
                exporter.shutdown(timeout)
            except Exception as err:
                logger.warning("%s failed to shut down: %s", type(exporter).__name__, err)


_pipeline: ExportPipeline | None = None
_pipeline_lock = threading.Lock()
_atexit_registered = False


def exporters_from_config() -> list[Exporter]:
    """The exporters the settings name: ``export_otlp_endpoint``, ``export_jsonl_path`` and
    ``export_http_url`` (config file or ``REGSHIELD_EXPORT_*``). The HTTP exporter's headers
    come from ``REGSHIELD_EXPORT_HTTP_HEADERS`` (``Name=value,Other=value``), never the file."""
    from regression_shield.config import setting

    capture = bool(setting("export_capture_content"))
    exporters: list[Exporter] = []
    endpoint = setting("export_otlp_endpoint")
    if endpoint:
        exporters.append(OpenTelemetryExporter(endpoint=str(endpoint), service_name=str(setting("export_service_name")),
                                               capture_content=capture))
    path = setting("export_jsonl_path")
    if path:
        exporters.append(JSONLExporter(str(path), capture_content=capture))
    url = setting("export_http_url")
    if url:
        headers = {}
        for pair in os.environ.get("REGSHIELD_EXPORT_HTTP_HEADERS", "").split(","):
            name, separator, value = pair.partition("=")
            if separator and name.strip():
                headers[name.strip()] = value.strip()
        exporters.append(HTTPExporter(str(url), headers=headers, capture_content=capture))
    return exporters


def export_traces(*exporters: Exporter, sample_rate: float | None = None, keep_errors: bool | None = None,
                  max_runs_per_minute: int | None = None, max_events_per_run: int | None = None,
                  pricing: dict[str, Any] | None = None) -> ExportPipeline:
    """Stream every recorder's runs to ``exporters`` from now on (replacing earlier exporters).
    With no exporters, the ones the settings name are used (see ``exporters_from_config``).

    ``sample_rate``: share of runs exported (default 1.0 = all). ``keep_errors``: also export
    runs that weren't sampled once something goes wrong in them (default on).
    ``max_runs_per_minute`` and ``max_events_per_run`` protect your backend from a flood.
    ``pricing`` prices model calls for the cost in each event (the config file's prices are
    used too). Options left as None come from the settings (``export_sample_rate``...).
    """
    from regression_shield.config import apply_log_level, setting

    global _pipeline, _atexit_registered
    apply_log_level()
    if not exporters:
        exporters = tuple(exporters_from_config())
        if not exporters:
            raise ValueError("export_traces needs at least one exporter: pass one, or set export_otlp_endpoint, "
                             "export_jsonl_path or export_http_url in your config (or REGSHIELD_EXPORT_*)")
    pipeline = ExportPipeline(list(exporters), sample_rate=setting("export_sample_rate", sample_rate),
                              keep_errors=bool(setting("export_keep_errors", keep_errors)),
                              max_runs_per_minute=setting("export_max_runs_per_minute", max_runs_per_minute),
                              max_events_per_run=max_events_per_run, pricing=pricing)
    with _pipeline_lock:
        previous, _pipeline = _pipeline, pipeline
        if not _atexit_registered:
            atexit.register(_shutdown_at_exit)
            _atexit_registered = True
    if previous is not None:
        previous.shutdown()
    return pipeline


def stop_exporting(timeout: float = 5.0) -> None:
    """Flush the exporters and stop exporting."""
    global _pipeline
    with _pipeline_lock:
        pipeline, _pipeline = _pipeline, None
    if pipeline is not None:
        pipeline.shutdown(timeout)


def current_pipeline() -> ExportPipeline | None:
    return _pipeline


def export_stats() -> dict[str, int]:
    """Counters since ``export_traces``: runs started, exported, sampled out, kept for
    errors, rate limited; events exported and dropped; exporter errors."""
    pipeline = _pipeline
    return dict(pipeline.stats) if pipeline else {}


def _shutdown_at_exit() -> None:
    pipeline = _pipeline
    if pipeline is not None:
        pipeline.shutdown(timeout=2.0)


# -- exporters --------------------------------------------------------------------------

class JSONLExporter(Exporter):
    """Appends one JSON event per line to a file. With ``capture_content=True`` the
    ``run_end`` event carries the whole trace, ready for a scenario file."""

    def __init__(self, path: str | os.PathLike[str], *, capture_content: bool = False):
        self.path = os.fspath(path)
        self.capture_content = capture_content
        self._file: Any = None
        self._lock = threading.Lock()

    def export(self, event: dict[str, Any]) -> None:
        line = json.dumps(self.visible(event), default=str, ensure_ascii=False)
        with self._lock:
            if self._file is None:
                directory = os.path.dirname(os.path.abspath(self.path))
                os.makedirs(directory, exist_ok=True)
                self._file = open(self.path, "a", encoding="utf-8")  # kept open between events
            self._file.write(line + "\n")
            self._file.flush()

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


class HTTPExporter(Exporter):
    """POSTs events as ``{"events": [...]}`` JSON batches to ``url`` from a background
    thread. Failed batches are retried; when the queue is full, new events are dropped
    (counted in ``dropped``) rather than slowing the agent."""

    def __init__(self, url: str, *, headers: dict[str, str] | None = None, capture_content: bool = False,
                 batch_size: int = 100, flush_interval: float = 1.0, timeout: float = 10.0,
                 max_queue: int = 10_000, retries: int = 3):
        self.url = url
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.capture_content = capture_content
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.timeout = timeout
        self.retries = retries
        self.dropped = 0
        self.sent = 0
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def export(self, event: dict[str, Any]) -> None:
        self._ensure_thread()
        try:
            self._queue.put_nowait(self.visible(event))
        except queue.Full:
            self.dropped += 1

    def _ensure_thread(self) -> None:
        if self._thread is None:
            with self._start_lock:
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name="regshield-http-exporter", daemon=True)
                    self._thread.start()

    def _run(self) -> None:
        import httpx

        with httpx.Client(timeout=self.timeout) as client:
            while not (self._stop.is_set() and self._queue.empty()):
                batch = self._next_batch()
                if batch:
                    self._post(client, batch)
                    for _ in batch:
                        self._queue.task_done()

    def _next_batch(self) -> list[dict[str, Any]]:
        try:
            batch = [self._queue.get(timeout=self.flush_interval)]
        except queue.Empty:
            return []
        while len(batch) < self.batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _post(self, client: Any, batch: list[dict[str, Any]]) -> None:
        body = json.dumps({"events": batch}, default=str).encode("utf-8")
        for attempt in range(self.retries + 1):
            try:
                response = client.post(self.url, content=body, headers=self.headers)
                if response.status_code < 400:
                    self.sent += len(batch)
                    return
                if response.status_code < 500 and response.status_code != 429:
                    break  # the server rejects it; retrying won't help
            except Exception as err:  # network errors: retry
                if attempt == self.retries:
                    logger.warning("HTTPExporter could not reach %s: %s", self.url, err)
            if attempt < self.retries:
                time.sleep(min(0.5 * 2 ** attempt, 5.0))
        self.dropped += len(batch)
        logger.warning("HTTPExporter dropped %d event(s) for %s", len(batch), self.url)

    def flush(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)

    def shutdown(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)


class OpenTelemetryExporter(Exporter):
    """Turns runs into OpenTelemetry spans: ``invoke_agent`` for the run, with an
    ``execute_tool`` span per tool call and a ``chat`` span per model call, using the
    GenAI semantic-convention attributes (plus ``regshield.*`` ones for cost and guards).

    Where spans go, first match wins:
      - ``tracer_provider``: your own provider;
      - ``span_exporter``: any OpenTelemetry span exporter, batched;
      - ``endpoint``: an OTLP/HTTP collector, e.g. ``http://localhost:4318``
        (``headers`` for auth), or the ``OTEL_EXPORTER_OTLP_*`` environment variables;
      - otherwise the global provider your app already set up.
    A run that starts inside one of your spans becomes its child. Needs
    ``pip install "regression-shield[otel]"``.
    """

    def __init__(self, *, endpoint: str | None = None, headers: dict[str, str] | None = None,
                 service_name: str = "regshield-agent", tracer_provider: Any = None, span_exporter: Any = None,
                 capture_content: bool = False):
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as err:
            raise ImportError('OpenTelemetryExporter needs OpenTelemetry: pip install "regression-shield[otel]"') from err
        self.capture_content = capture_content
        self._own_provider = None
        if tracer_provider is None and (span_exporter is not None or endpoint or _otlp_env_set()):
            if span_exporter is None:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                if endpoint and not endpoint.rstrip("/").endswith("/v1/traces"):
                    endpoint = endpoint.rstrip("/") + "/v1/traces"
                span_exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
            tracer_provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
            tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
            self._own_provider = tracer_provider
        self._provider = tracer_provider or trace.get_tracer_provider()
        self._tracer = self._provider.get_tracer("regression_shield")
        self._runs: dict[str, Any] = {}
        self._lock = threading.Lock()

    def export(self, event: dict[str, Any]) -> None:
        kind = event["event"]
        if kind == "run_start":
            self._root(event)
        elif kind == "run_end":
            self._end_run(event)
        elif kind in ("tool_call", "llm_call"):
            self._child(event)
        else:
            root = self._root(event)
            attributes = {f"regshield.{key}": _attr(value) for key, value in event.items()
                          if key not in ("event", "run_id", "ts", "content") and value is not None}
            if self.capture_content and event.get("content"):
                attributes["regshield.content"] = _attr(event["content"])
            root.add_event(kind, attributes=attributes, timestamp=_ns(event["ts"]))

    def _root(self, event: dict[str, Any]) -> Any:
        from opentelemetry.trace import SpanKind

        with self._lock:
            span = self._runs.get(event["run_id"])
            if span is None:
                agent = event.get("agent") or event.get("name") or "agent"
                attributes = {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": str(agent),
                              "regshield.run_id": event["run_id"]}
                if event.get("name"):
                    attributes["regshield.run.name"] = str(event["name"])
                for key, value in (event.get("attributes") or {}).items():
                    attributes[f"regshield.{key}"] = _attr(value)
                span = self._tracer.start_span(f"invoke_agent {agent}", kind=SpanKind.INTERNAL,
                                               attributes=attributes, start_time=_ns(event["ts"]))
                self._runs[event["run_id"]] = span
            return span

    def _child(self, event: dict[str, Any]) -> None:
        from opentelemetry import trace
        from opentelemetry.trace import SpanKind, Status, StatusCode

        root = self._root(event)
        context = trace.set_span_in_context(root)
        if event["event"] == "tool_call":
            name = f"execute_tool {event['tool']}"
            attributes: dict[str, Any] = {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": event["tool"],
                                          "regshield.step": event.get("step") or 0, "regshield.status": event["status"]}
            for key in ("agent", "node", "blocked_rule", "warning_rule", "cost_usd", "parallel_group"):
                if event.get(key) is not None:
                    attributes["gen_ai.agent.name" if key == "agent" else f"regshield.{key}"] = _attr(event[key])
            content = event.get("content") or {}
            if self.capture_content:
                if "args" in content:
                    attributes["gen_ai.tool.call.arguments"] = _attr(content["args"])
                if "observation" in content:
                    attributes["gen_ai.tool.call.result"] = _attr(content["observation"])
                if content.get("thought"):
                    attributes["regshield.thought"] = _attr(content["thought"])
        else:
            name = f"chat {event.get('model')}"
            attributes = {"gen_ai.operation.name": "chat", "gen_ai.request.model": str(event.get("model")),
                          "gen_ai.usage.input_tokens": event.get("input_tokens", 0),
                          "gen_ai.usage.output_tokens": event.get("output_tokens", 0)}
            if event.get("cached_input_tokens"):
                attributes["gen_ai.usage.cache_read.input_tokens"] = event["cached_input_tokens"]
            if event.get("cache_write_tokens"):
                attributes["gen_ai.usage.cache_creation.input_tokens"] = event["cache_write_tokens"]
            if event.get("cost_usd") is not None:
                attributes["regshield.cost_usd"] = event["cost_usd"]
            if event.get("agent"):
                attributes["gen_ai.agent.name"] = str(event["agent"])
        span = self._tracer.start_span(name, context=context, kind=SpanKind.INTERNAL, attributes=attributes,
                                       start_time=_ns(event.get("ts_start", event["ts"])))
        if event.get("status") in ("error", "blocked"):
            span.set_status(Status(StatusCode.ERROR, "blocked by policy" if event["status"] == "blocked" else "tool failed"))
        span.end(end_time=_ns(event["ts"]))

    def _end_run(self, event: dict[str, Any]) -> None:
        from opentelemetry.trace import Status, StatusCode

        root = self._root(event)
        with self._lock:
            self._runs.pop(event["run_id"], None)
        for key in ("status", "tool_calls", "errors", "blocked", "llm_calls", "cost_usd", "truncated"):
            if event.get(key) is not None:
                root.set_attribute(f"regshield.run.{key}", _attr(event[key]))
        if event.get("input_tokens") is not None:
            root.set_attribute("gen_ai.usage.input_tokens", event["input_tokens"])
            root.set_attribute("gen_ai.usage.output_tokens", event.get("output_tokens", 0))
        content = event.get("content") or {}
        if self.capture_content and content.get("final_response"):
            root.set_attribute("regshield.final_response", _attr(content["final_response"]))
        if event.get("status") not in (None, "ok"):
            root.set_status(Status(StatusCode.ERROR, event.get("error_type") or str(event["status"])))
        root.end(end_time=_ns(event["ts"]))

    def flush(self, timeout: float = 5.0) -> None:
        force_flush = getattr(self._provider, "force_flush", None)
        if force_flush is not None:
            force_flush(int(timeout * 1000))

    def shutdown(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        if self._own_provider is not None:
            self._own_provider.shutdown()


def _otlp_env_set() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _ns(seconds: float) -> int:
    return int(seconds * 1_000_000_000)


def _attr(value: Any) -> Any:
    """An OpenTelemetry attribute value: numbers and booleans as they are, anything else as text."""
    if isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "...[truncated]"
