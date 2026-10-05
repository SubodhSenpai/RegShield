"""``regshield`` command line: evaluate scenario files, run the demo, serve the dashboard,
update the model prices used for cost (``regshield pricing refresh``), and see or start
your settings file (``regshield config show`` / ``init``).

Scenario file format (JSON): a list of items, each with a scenario and the trace to check::

    [{"scenario": {"scenario_id": "deploy_gate", "expected_order": ["test", "deploy"]},
      "trace": [{"action": {"name": "test", "args": {}}, "observation": "ok"}]}]

An item may also carry a ``regression_trace`` (a known-bad variant); the dashboard
shows both side by side. Instead of ``trace``, an item can hold ``traces``: several
recorded runs of the same task, which must pass at ``--min-pass-rate`` (default: all).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from typing import Any

from regression_shield import __version__
from regression_shield.config import DEFAULTS
from regression_shield.core.cost import format_usd
from regression_shield.core.evaluator import JUDGE_ON_ERROR_CHOICES, AgentTraceEvaluator
from regression_shield.log import enable_logging
from regression_shield.models import DEFAULT_REPORT_PATH, EvaluationReport, RunsReport, save_reports

logger = logging.getLogger(__name__)


def load_scenario_file(path: str) -> list[dict[str, Any]]:
    """Items of a scenario file, validated: each needs a 'scenario' and a 'trace' (or 'traces')."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else [data]
    for number, item in enumerate(items, 1):
        missing = [key for key in ("scenario", "trace") if not isinstance(item, dict) or
                   (key not in item and not (key == "trace" and "traces" in item))]
        if missing:
            raise ValueError(f"{path}: item {number} is missing {missing}. Each item needs 'scenario' and "
                             "'trace' (or 'traces', a list of recorded runs).")
        if "trace" in item and "traces" in item:
            raise ValueError(f"{path}: item {number} has both 'trace' and 'traces'; use one.")
        if "traces" in item and (not isinstance(item["traces"], list) or not item["traces"]):
            raise ValueError(f"{path}: item {number}: 'traces' must be a non-empty list of traces.")
    logger.debug("Loaded %d scenario(s) from %s", len(items), path)
    return items


def _print_report(report: EvaluationReport, indent: str = "      ") -> None:
    if report.patterns:
        print(indent + "patterns: " + ", ".join(
            f"{p['label']} {'PASS' if p['passed'] else 'FAIL'}" for p in report.patterns.values()))
    if report.judge_audit:
        score = report.judge_audit.get("score")
        print(f"{indent}LLM judge ({report.judge_audit.get('model')}): "
              f"{f'{score:.2f}' if isinstance(score, (int, float)) else 'n/a'}  {report.judge_audit.get('reasoning', '')}")
    for failure in report.failures:
        print(f"{indent}- {failure}")
    for warning in report.warnings:
        print(f"{indent}warning: {warning}")


def run_file(path: str, evaluator: AgentTraceEvaluator, report_path: str | None = DEFAULT_REPORT_PATH,
             min_pass_rate: float | None = None) -> int:
    """Evaluate every item in a scenario file, print the results, and return the exit code."""
    items = load_scenario_file(path)
    print(f"Evaluating {len(items)} scenario(s) from {path}\n")

    results: list[EvaluationReport | RunsReport] = []
    saved: list[EvaluationReport] = []  # what the dashboard shows: one report per trace
    regressions: list[EvaluationReport] = []
    routes_checked = routes_correct = 0
    for item in items:
        if "traces" in item:
            runs = evaluator.evaluate_runs(item["scenario"], item["traces"], min_pass_rate=min_pass_rate)
            results.append(runs)
            mark = "PASS" if runs.passed else "FAIL"
            name = "  ".join(part for part in (runs.scenario_id, runs.title) if part)
            required = "" if runs.passed else f", required {runs.min_pass_rate:.0%}"
            print(f"{mark}  {name}  ({runs.passed_runs}/{runs.runs} runs passed{required})")
            for kind, count in runs.failure_counts.items():
                print(f"      - {kind} in {count}/{runs.runs} runs")
            for number, report in enumerate(runs.reports, 1):
                saved.append(dataclasses.replace(report, scenario_id=f"{report.scenario_id} [run {number}/{runs.runs}]"))
            reports = runs.reports
        else:
            report = evaluator.evaluate(item["scenario"], item["trace"])
            results.append(report)
            saved.append(report)
            mark = "PASS" if report.passed else "FAIL"
            name = "  ".join(part for part in (report.scenario_id, report.title) if part)
            print(f"{mark}  {name}  (composite {report.composite_score:.2f})")
            _print_report(report)
            reports = [report]
        if "regression_trace" in item:
            regressions.append(evaluator.evaluate(item["scenario"], item["regression_trace"]))

        for report in reports:
            routing = report.patterns.get("routing")
            if routing and routing["details"].get("expected_route") is not None:
                routes_checked += 1
                routes_correct += routing["passed"]

    # A regression_trace is a known-bad trace: if it passes, the scenario can't catch that regression
    missed = [r for r in regressions if r.passed]
    for report in missed:
        print(f"MISS  {report.scenario_id}  its regression_trace passed; the scenario doesn't catch it")

    passed = sum(r.passed for r in results)
    summary = f"\n{passed}/{len(results)} scenario(s) passed."
    if regressions:
        summary += f" Regressed traces caught: {len(regressions) - len(missed)}/{len(regressions)}."
    if routes_checked:
        summary += f" Routing accuracy: {routes_correct}/{routes_checked} ({routes_correct / routes_checked:.0%})."
    print(summary)
    _print_costs(saved)
    if report_path:
        saved_path = save_reports(saved, report_path, regression_reports=regressions, replace=True)
        print(f"Report saved to {saved_path}")
    return 0 if passed == len(results) and not missed else 1


def _print_costs(reports: list[EvaluationReport]) -> None:
    """What the recorded runs cost, and what the LLM judge cost, when anything was recorded."""
    costs = [report.cost for report in reports if report.cost]
    if costs:
        total = sum(cost["total_usd"] for cost in costs)
        calls = sum(cost["llm_calls"] for cost in costs)
        tokens = sum(cost["total_tokens"] for cost in costs)
        unpriced = sorted({model for cost in costs for model in cost["unpriced_models"]})
        line = f"Cost of the recorded runs: {format_usd(total)} ({calls} LLM calls, {tokens:,} tokens)"
        if unpriced:
            line += f"; no price for {', '.join(repr(model) for model in unpriced)}"
        print(line)
    audits = [report.judge_audit for report in reports if report.judge_audit and report.judge_audit.get("usage")]
    if audits:
        tokens = sum(a["usage"]["input_tokens"] + a["usage"]["output_tokens"] for a in audits)
        priced = [a["cost_usd"] for a in audits if "cost_usd" in a]
        cost = f", {format_usd(sum(priced))}" if priced else ""
        print(f"LLM judge: {len(audits)} calls, {tokens:,} tokens{cost}")


def _add_judge_options(group: argparse._ArgumentGroup) -> None:
    group.add_argument("--llm-judge", dest="llm_judge", action="store_true", default=None,
                       help="also have an LLM judge each trace (needs an API key)")
    group.add_argument("--no-llm-judge", dest="llm_judge", action="store_false",
                       help="don't use the judge, even if the config file turns it on")
    group.add_argument("--api-key", help="judge API key (default: OPENROUTER_API_KEY or OPENAI_API_KEY)")
    group.add_argument("--model", help="judge model (default: JUDGE_MODEL, the config file, or an OpenRouter free model)")
    group.add_argument("--base-url", help="OpenAI-compatible endpoint (default: OpenRouter)")
    group.add_argument("--judge-timeout", type=float, metavar="SECONDS",
                       help="seconds to wait for each judge reply (default: JUDGE_TIMEOUT, the config file, or 30)")
    group.add_argument("--judge-on-error", choices=JUDGE_ON_ERROR_CHOICES,
                       help="when the judge can't give a verdict: fail the scenario (default) or pass it")


def _add_evaluation_options(parser: argparse.ArgumentParser) -> None:
    thresholds = parser.add_argument_group("thresholds (default: the config file, then the value shown)")
    for metric in ("tool-selection", "argument-correctness", "call-ordering", "step-efficiency",
                   "reasoning-faithfulness"):
        default = DEFAULTS[f"min_{metric.replace('-', '_')}"]
        thresholds.add_argument(f"--min-{metric}", type=float, metavar="SCORE",
                                help=f"minimum {metric.replace('-', ' ')} (default {default})")
    thresholds.add_argument("--min-pass-rate", type=float, metavar="RATE",
                            help="for items with several 'traces': share of runs that must pass (default 1.0)")
    _add_judge_options(parser.add_argument_group("LLM judge (optional)"))
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
        judge_timeout=args.judge_timeout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regshield", description="Regression tests for AI agent execution traces.",
        epilog="Settings can also live in regshield.toml or [tool.regshield] in pyproject.toml.")
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
    _add_judge_options(serve.add_argument_group("LLM judge for traces sent to the API (optional)"))

    pricing = commands.add_parser("pricing", help="update or look up the model prices used for cost")
    pricing_commands = pricing.add_subparsers(dest="pricing_command", required=True)
    refresh = pricing_commands.add_parser("refresh", parents=[common],
                                          help="download the latest list prices (LiteLLM's price list)")
    refresh.add_argument("--from", dest="source", metavar="FILE_OR_URL",
                         help="read a copy of LiteLLM's model_prices_and_context_window.json instead of downloading it")
    refresh.add_argument("--output", metavar="PATH",
                         help="where to save the list (default: your user cache, which RegShield then uses)")
    show = pricing_commands.add_parser("show", parents=[common], help="show the price RegShield uses for models")
    show.add_argument("models", nargs="+", metavar="MODEL")

    config = commands.add_parser("config", help="see or start your settings file")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("show", parents=[common],
                               help="every setting in effect, and where it comes from (file, environment, default)")
    init = config_commands.add_parser("init", parents=[common],
                                      help="write regshield.toml with every setting, and .env.example for API keys")
    init.add_argument("--dir", default=".", help="where to write them (default: the current directory)")
    init.add_argument("--force", action="store_true", help="overwrite files that already exist")
    return parser


def _shown(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):  # pricing tables
        models, tools = value.get("models") or {}, value.get("tools") or {}
        return f"{len(models)} model price(s), {len(tools)} tool price(s)"
    return str(value)


def run_config(args: argparse.Namespace) -> int:
    """``regshield config show`` and ``regshield config init``."""
    import os

    from regression_shield import config as settings
    from regression_shield.core.judge import LLMJudge

    if args.config_command == "init":
        targets = ((os.path.join(args.dir, "regshield.toml"), settings.CONFIG_TEMPLATE),
                   (os.path.join(args.dir, ".env.example"), settings.ENV_TEMPLATE))
        for path, text in targets:
            if os.path.exists(path) and not args.force:
                print(f"{path} already exists; left as it is (--force overwrites it)")
                continue
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"Wrote {path}")
        gitignore = os.path.join(args.dir, ".gitignore")
        ignored = False
        if os.path.exists(gitignore):
            with open(gitignore, encoding="utf-8") as f:
                ignored = any(line.strip() in (".env", "/.env", ".env*", "*.env") for line in f)
        print("\nNext: uncomment the settings you need in regshield.toml. For API keys, copy .env.example to .env, "
              'fill it in and set env_file = ".env".' + ("" if ignored else " Add .env to .gitignore so keys stay out of git."))
        print("Check the result with `regshield config show`.")
        return 0

    config_path = settings.find_config_file()
    config = settings.load_config()
    print(f"Config file: {os.path.abspath(config_path) if config_path else 'none (all defaults; `regshield config init` writes one)'}")
    env_file = settings.env_setting("env_file") or config.get("env_file")
    if env_file:
        print(f"Env file:    {env_file}")
    print("\nSetting (highest priority first: arguments, environment, file, defaults)")
    project = os.path.dirname(os.path.abspath(config_path)) if config_path else os.getcwd()
    for name in settings.SETTINGS:
        value, source = settings.setting_source(name, config, config_path)
        if isinstance(value, str) and os.path.isabs(value) and os.path.abspath(value).startswith(project + os.sep):
            value = os.path.relpath(value, project)  # paths inside the project, kept short
        print(f"  {name:<28} {_shown(value):<34} {source}")
    print("\nAPI keys (never stored in the config file)")
    for variable in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        origin = settings.env_file_variables.get(variable)
        state = (f"set (from {os.path.basename(origin)})" if origin else "set") if os.environ.get(variable) else "not set"
        print(f"  {variable:<28} {state}")
    judge = LLMJudge()
    key = "your own server, no key needed" if judge.self_hosted else ("key set" if judge.api_key else "needs a key")
    print(f"\nLLM judge would use: {judge.model} at {judge.base_url} ({key})")
    return 0


def _per_million(prices: list[float | None]) -> str:
    text = f"${prices[0]:g} in / ${prices[1]:g} out"
    if prices[2] is not None:
        text += f" / ${prices[2]:g} cached"
    return text


def run_pricing(args: argparse.Namespace) -> int:
    """``regshield pricing refresh`` and ``regshield pricing show``."""
    from regression_shield.config import load_config
    from regression_shield.core.cost import merge_pricing, price_for, price_list_path, refresh_prices, snapshot_date

    if args.pricing_command == "refresh":
        print(f"Reading {args.source}" if args.source else "Downloading LiteLLM's price list...")
        result = refresh_prices(args.source, args.output)
        print(f"Saved prices for {result['models']:,} models (as of {result['prices_as_of']}) to {result['path']}")
        changed = result["changed"]
        print(f"Since the previous list ({result['previous_as_of']}): {len(result['added'])} new, "
              f"{len(changed)} changed, {len(result['removed'])} removed")
        for name, (old, new) in list(changed.items())[:10]:
            print(f"  {name}: {_per_million(old)} -> {_per_million(new)} per 1M tokens")
        if len(changed) > 10:
            print(f"  ... and {len(changed) - 10} more")
        if result["in_use"]:
            print("RegShield now prices calls with this list.")
        else:
            print(f"To use it, set REGSHIELD_PRICE_LIST={result['path']}")
        return 0

    pricing = merge_pricing(load_config().get("pricing"))
    print(f"Price list: {price_list_path()} (prices as of {snapshot_date()})")
    missing = 0
    for model in args.models:
        price = price_for(model, pricing)
        if price is None:
            missing += 1
            print(f"  {model}: no price; add it under [tool.regshield.pricing.models]")
            continue
        if price.source == "local":
            print(f"  {model}: free, a local model (give it a price to estimate what your GPU costs)")
            continue
        where = "your pricing" if price.source == "pricing" else "price list"
        prices = [price.input, price.output, price.cached_input, price.cache_write]
        print(f"  {model}: {_per_million(prices)} per 1M tokens ({where}: {price.key})")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    enable_logging("DEBUG" if args.verbose else "WARNING")
    try:
        if not args.verbose and args.command != "config":
            from regression_shield.config import setting

            configured = setting("log_level")
            if configured:
                enable_logging(configured)
        if args.command == "config":
            return run_config(args)
        if args.command == "pricing":
            return run_pricing(args)
        if args.command == "eval":
            return run_file(args.file, _evaluator(args), args.report, args.min_pass_rate)
        if args.command == "demo":
            from regression_shield.server import SAMPLE_SCENARIOS_FILE
            return run_file(SAMPLE_SCENARIOS_FILE, _evaluator(args), args.report, args.min_pass_rate)
        from regression_shield.server import start_server
        start_server(port=args.port, host=args.host, open_browser=args.open_browser, use_llm_judge=args.llm_judge,
                     api_key=args.api_key, model=args.model, base_url=args.base_url,
                     judge_on_error=args.judge_on_error, judge_timeout=args.judge_timeout)
        return 0
    except (OSError, ValueError) as err:  # missing file, bad JSON or scenario, bad configuration
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
