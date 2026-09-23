"""RegShield: regression tests for AI agent execution traces.

Checks what an agent did (which tools ran, in what order, with which
arguments, and what it concluded) against a scenario, plus agentic patterns:
policy rules, human approval, plan-and-execute, multi-agent handoffs,
routing, parallel calls, graph workflows and evaluator-optimizer loops.

    from regression_shield import evaluate_trace
    report = evaluate_trace(scenario, trace)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from regression_shield.adapters.decorator import shield
from regression_shield.adapters.smolagents import (
    extract_smolagents_trace,
    instrument_smolagents,
)
from regression_shield.core.evaluator import AgentTraceEvaluator, evaluate_trace
from regression_shield.core.judge import LLMJudge
from regression_shield.core.patterns import run_pattern_checks
from regression_shield.log import enable_logging
from regression_shield.models import (
    EvaluationFailed,
    EvaluationReport,
    ScenarioSpec,
    StepTrace,
    save_reports,
)
from regression_shield.recorder import TraceRecorder

if TYPE_CHECKING:  # for type checkers and IDEs; at runtime it's loaded by __getattr__ below
    from regression_shield.adapters.langchain import RegressionShieldCallbackHandler

__version__ = "0.4.0"

__all__ = [
    "AgentTraceEvaluator",
    "EvaluationFailed",
    "EvaluationReport",
    "LLMJudge",
    "RegressionShieldCallbackHandler",
    "ScenarioSpec",
    "StepTrace",
    "TraceRecorder",
    "enable_logging",
    "evaluate_trace",
    "extract_smolagents_trace",
    "instrument_smolagents",
    "run_pattern_checks",
    "save_reports",
    "shield",
]


def __getattr__(name: str) -> Any:
    # Imported on first use, so `import regression_shield` doesn't load LangChain
    if name == "RegressionShieldCallbackHandler":
        from regression_shield.adapters.langchain import RegressionShieldCallbackHandler
        return RegressionShieldCallbackHandler
    raise AttributeError(f"module 'regression_shield' has no attribute {name!r}")
