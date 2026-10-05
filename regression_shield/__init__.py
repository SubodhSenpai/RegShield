"""RegShield: regression tests for AI agent execution traces.

Checks what an agent did (which tools ran, in what order, with which
arguments, and what it concluded) against a scenario, plus agentic patterns:
policy rules, human approval, plan-and-execute, multi-agent handoffs,
routing, parallel calls, graph workflows and evaluator-optimizer loops.

    from regression_shield import evaluate_trace
    report = evaluate_trace(scenario, trace)

In production the same rules block risky actions as they happen (``Guard``),
``instrument()`` records OpenAI, Anthropic and Gemini SDK calls without code
changes, and ``export_traces`` streams runs to your monitoring service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from regression_shield.adapters.decorator import shield
from regression_shield.adapters.smolagents import (
    extract_smolagents_trace,
    instrument_smolagents,
)
from regression_shield.core.evaluator import AgentTraceEvaluator, evaluate_runs, evaluate_trace
from regression_shield.core.judge import LLMJudge
from regression_shield.core.patterns import run_pattern_checks
from regression_shield.export import (
    Exporter,
    HTTPExporter,
    JSONLExporter,
    OpenTelemetryExporter,
    export_stats,
    export_traces,
    stop_exporting,
)
from regression_shield.guard import ActionBlocked, Guard
from regression_shield.instrument import instrument, uninstrument
from regression_shield.log import enable_logging
from regression_shield.models import (
    EvaluationFailed,
    EvaluationReport,
    RunsReport,
    ScenarioSpec,
    StepTrace,
    save_reports,
)
from regression_shield.recorder import TraceRecorder, active_recorder

if TYPE_CHECKING:  # for type checkers and IDEs; at runtime it's loaded by __getattr__ below
    from regression_shield.adapters.langchain import RegressionShieldCallbackHandler

__version__ = "0.5.0"

__all__ = [
    "ActionBlocked",
    "AgentTraceEvaluator",
    "EvaluationFailed",
    "EvaluationReport",
    "Exporter",
    "Guard",
    "HTTPExporter",
    "JSONLExporter",
    "LLMJudge",
    "OpenTelemetryExporter",
    "RegressionShieldCallbackHandler",
    "RunsReport",
    "ScenarioSpec",
    "StepTrace",
    "TraceRecorder",
    "active_recorder",
    "enable_logging",
    "evaluate_runs",
    "evaluate_trace",
    "export_stats",
    "export_traces",
    "extract_smolagents_trace",
    "instrument",
    "instrument_smolagents",
    "run_pattern_checks",
    "save_reports",
    "shield",
    "stop_exporting",
    "uninstrument",
]


def __getattr__(name: str) -> Any:
    # Imported on first use, so `import regression_shield` doesn't load LangChain
    if name == "RegressionShieldCallbackHandler":
        from regression_shield.adapters.langchain import RegressionShieldCallbackHandler
        return RegressionShieldCallbackHandler
    raise AttributeError(f"module 'regression_shield' has no attribute {name!r}")
