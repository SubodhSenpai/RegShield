"""``regshield`` command line: evaluate scenario files, run the demo, serve the dashboard.

Scenario file format (JSON): a list of items, each with a scenario and the trace to check::

    [{"scenario": {"scenario_id": "deploy_gate", "expected_order": ["test", "deploy"]},
      "trace": [{"action": {"name": "test", "args": {}}, "observation": "ok"}]}]

An item may also carry a ``regression_trace`` (a known-bad variant); the dashboard
shows both side by side.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from regression_shield import __version__
from regression_shield.core.evaluator import JUDGE_ON_ERROR_CHOICES, AgentTraceEvaluator
from regression_shield.log import enable_logging
from regression_shield.models import DEFAULT_REPORT_PATH, EvaluationReport, save_reports

logger = logging.getLogger(__name__)


def load_scenario_file(path: str) -> list[dict[str, Any]]:
    """Items of a scenario file, validated: each needs a 'scenario' and a 'trace'."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else [data]
    for number, item in enumerate(items, 1):
        missing = [key for key in ("scenario", "trace") if not isinstance(item, dict) or key not in item]
        if missing:
            raise ValueError(f"{path}: item {number} is missing {missing}. Each item needs 'scenario' and 'trace'.")
    logger.debug("Loaded %d scenario(s) from %s", len(items), path)
    return items


def run_file(path: str, evaluator: AgentTraceEvaluator, report_path: str | None = DEFAULT_REPORT_PATH) -> int:
    """Evaluate every item in a scenario file, print the results, and return the exit code."""
    items = load_scenario_file(path)
    print(f"Evaluating {len(items)} scenario(s) from {path}\n")

    reports: list[EvaluationReport] = []
    regressions: list[EvaluationReport] = []
    routes_checked = routes_correct = 0
    for item in items:
        report = evaluator.evaluate(item["scenario"], item["trace"])
        reports.append(report)
        if "regression_trace" in item:
            regressions.append(evaluator.evaluate(item["scenario"], item["regression_trace"]))

        mark = "PASS" if report.passed else "FAIL"
        name = "  ".join(part for part in (report.scenario_id, report.title) if part)
        print(f"{mark}  {name}  (composite {report.composite_score:.2f})")
        if report.patterns:
            print("      patterns: " + ", ".join(
                f"{p['label']} {'PASS' if p['passed'] else 'FAIL'}" for p in report.patterns.values()))
        if report.judge_audit:
            score = report.judge_audit.get("score")
            print(f"      LLM judge ({report.judge_audit.get('model')}): "
                  f"{f'{score:.2f}' if isinstance(score, (int, float)) else 'n/a'}  {report.judge_audit.get('reasoning', '')}")
        for failure in report.failures:
            print(f"      - {failure}")

        routing = report.patterns.get("routing")
        if routing and routing["details"].get("expected_route") is not None:
            routes_checked += 1
            routes_correct += routing["passed"]

    # A regression_trace is a known-bad trace: if it passes, the scenario can't catch that regression
    missed = [r for r in regressions if r.passed]
    for report in missed:
        print(f"MISS  {report.scenario_id}  its regression_trace passed; the scenario doesn't catch it")

    passed = sum(r.passed for r in reports)
    summary = f"\n{passed}/{len(reports)} scenario(s) passed."
    if regressions:
        summary += f" Regressed traces caught: {len(regressions) - len(missed)}/{len(regressions)}."
    if routes_checked:
        summary += f" Routing accuracy: {routes_correct}/{routes_checked} ({routes_correct / routes_checked:.0%})."
    print(summary)
    if report_path:
        saved = save_reports(reports, report_path, regression_reports=regressions, replace=True)
        print(f"Report saved to {saved}")
    return 0 if passed == len(reports) and not missed else 1


def _add_evaluation_options(parser: argparse.ArgumentParser) -> None:
    thresholds = parser.add_argument_group("thresholds")
    for metric, default in (("tool-selection", 0.85), ("argument-correctness", 0.85), ("call-ordering", 1.0),
                            ("step-efficiency", 0.70), ("reasoning-faithfulness", 0.85)):
        thresholds.add_argument(f"--min-{metric}", type=float, default=default, metavar="SCORE",
                                help=f"minimum {metric.replace('-', ' ')} (default {default})")
    judge = parser.add_argument_group("LLM judge (optional)")
    judge.add_argument("--llm-judge", action="store_true",
                       help="also have an LLM judge each trace (needs an API key)")
    judge.add_argument("--api-key", help="judge API key (default: OPENROUTER_API_KEY or OPENAI_API_KEY)")
    judge.add_argument("--model", help="judge model (default: JUDGE_MODEL or an OpenRouter free model)")
    judge.add_argument("--base-url", help="OpenAI-compatible endpoint (default: OpenRouter)")
    judge.add_argument("--judge-on-error", choices=JUDGE_ON_ERROR_CHOICES, default="fail",
                       help="when the judge can't give a verdict: fail the scenario (default) or pass it")
    parser.add_argument("--report", default=DEFAULT_REPORT_PATH, metavar="PATH",
                        help=f"where to save the report for the dashboard (default {DEFAULT_REPORT_PATH})")


def _evaluator(args: argparse.Namespace) -> AgentTraceEvaluator:
    return AgentTraceEvaluator(
        min_tool_selection=args.min_tool_selection,
        min_argument_correctness=args.min_argument_correctness,
        min_call_ordering=args.min_call_ordering,
        min_step_efficiency=args.min_step_efficiency,
        min_reasoning_faithfulness=args.min_reasoning_faithfulness,
        use_llm_judge=args.llm_judge,
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        judge_on_error=args.judge_on_error,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="regshield", description="Regression tests for AI agent execution traces.")
    parser.add_argument("--version", action="version", version=f"regshield {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true",
                        help="show debug logs: every metric, pattern check, judge call and request")
    commands = parser.add_subparsers(dest="command", required=True)

    evaluate = commands.add_parser("eval", parents=[common], help="evaluate a scenario file (exit code 1 if any fail)")
    evaluate.add_argument("file", help="JSON file of {scenario, trace} items")
    _add_evaluation_options(evaluate)

    demo = commands.add_parser("demo", parents=[common], help="evaluate the bundled sample scenarios")
    _add_evaluation_options(demo)

    serve = commands.add_parser("serve", parents=[common], help="start the local dashboard")
    serve.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    serve.add_argument("--host", default="127.0.0.1",
                       help="interface to listen on (default 127.0.0.1: this machine only). "
                            "0.0.0.0 allows other machines; the dashboard has no authentication")
    serve.add_argument("--no-open", dest="open_browser", action="store_false", help="don't open a browser")
    serve.add_argument("--llm-judge", action="store_true", help="judge traces sent to the API with an LLM")
    serve.add_argument("--api-key", help="judge API key")
    serve.add_argument("--model", help="judge model")
    serve.add_argument("--base-url", help="OpenAI-compatible endpoint for the judge")
    serve.add_argument("--judge-on-error", choices=JUDGE_ON_ERROR_CHOICES, default="fail")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    enable_logging("DEBUG" if args.verbose else "WARNING")
    try:
        if args.command == "eval":
            return run_file(args.file, _evaluator(args), args.report)
        if args.command == "demo":
            from regression_shield.server import SAMPLE_SCENARIOS_FILE
            return run_file(SAMPLE_SCENARIOS_FILE, _evaluator(args), args.report)
        from regression_shield.server import start_server
        start_server(port=args.port, host=args.host, open_browser=args.open_browser, use_llm_judge=args.llm_judge,
                     api_key=args.api_key, model=args.model, base_url=args.base_url,
                     judge_on_error=args.judge_on_error)
        return 0
    except (OSError, ValueError) as err:  # missing file, bad JSON or scenario, bad configuration
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
