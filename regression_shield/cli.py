"""Command-Line Interface for RegressionShield SDK (regshield CLI)."""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from regression_shield import evaluate_trajectory, AgentTrajectoryEvaluator


def run_eval_from_file(
    file_path: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    use_llm_judge: bool = False,
    min_tool_selection: float = 0.85,
    min_argument_correctness: float = 0.85,
    min_order_accuracy: float = 1.00,
    min_trajectory_efficiency: float = 0.70,
):
    """Evaluate scenarios and trajectories provided in a JSON file."""
    if not os.path.exists(file_path):
        print(f"[!] Error: File not found: {file_path}")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else [data]
    evaluator = AgentTrajectoryEvaluator(
        api_key=api_key,
        model=model,
        base_url=base_url,
        use_llm_judge=use_llm_judge,
        min_tool_selection=min_tool_selection,
        min_argument_correctness=min_argument_correctness,
        min_order_accuracy=min_order_accuracy,
        min_trajectory_efficiency=min_trajectory_efficiency,
    )

    print(f"\n[*] Evaluating {len(items)} Agent Trajectory Scenarios from {file_path}...")
    if model:
        print(f"[*] Judge Model: {model} (Endpoint: {base_url or 'https://openrouter.ai/api/v1'})")
    print()
    passed_count = 0

    for item in items:
        scenario = item.get("scenario") or item
        trajectory = item.get("trajectory") or item.get("steps") or item.get("baseline_trajectory")
        report = evaluator.evaluate_scenario(scenario, trajectory)

        status_tag = "[PASS]" if report["status"] == "PASSED" else "[FAIL]"
        print(f"{status_tag} [{report['status']}] {report['scenario_id']}: {report['title']} (Composite: {report['composite_score']:.2f})")
        
        if report.get("judge_audit") and report["judge_audit"].get("reasoning"):
            ja = report["judge_audit"]
            print(f"    [Judge {ja.get('model')}]: score={ja.get('score', 1.0):.2f} | {ja.get('reasoning')}")

        if report["failures"]:
            for fail in report["failures"]:
                print(f"    -> {fail}")
        else:
            passed_count += 1
        print()

    print(f"Overall Result: {passed_count}/{len(items)} scenarios passed.\n")


def start_server_command(
    port: int = 8000,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    use_llm_judge: bool = False,
):
    """Start the dynamic dashboard server with configured evaluator defaults."""
    from regression_shield.server import start_server
    start_server(
        port=port,
        api_key=api_key,
        model=model,
        base_url=base_url,
        use_llm_judge=use_llm_judge,
    )


def main():
    parser = argparse.ArgumentParser(
        prog="regshield",
        description="RegressionShield — Agentic AI Reasoning & Trajectory Evaluation CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: eval
    eval_parser = subparsers.add_parser("eval", help="Evaluate agent trajectories from a JSON file")
    eval_parser.add_argument("--file", "-f", required=True, help="Path to JSON file containing scenarios & trajectories")
    eval_parser.add_argument("--api-key", default=None, help="API key for LLM judge (or set OPENROUTER_API_KEY / OPENAI_API_KEY)")
    eval_parser.add_argument("--model", default=None, help="LLM judge model identifier (e.g. minimax/minimax-m2.7:free, gpt-4o-mini)")
    eval_parser.add_argument("--base-url", default=None, help="OpenAI-compatible API base URL (default: https://openrouter.ai/api/v1)")
    eval_parser.add_argument("--llm-judge", action="store_true", help="Enable LLM semantic reasoning judge")
    eval_parser.add_argument("--min-tool-selection", type=float, default=0.85, help="Minimum tool selection F1 (default: 0.85)")
    eval_parser.add_argument("--min-arg-correctness", type=float, default=0.85, help="Minimum argument schema accuracy (default: 0.85)")
    eval_parser.add_argument("--min-order-accuracy", type=float, default=1.00, help="Minimum tool ordering accuracy (default: 1.00)")
    eval_parser.add_argument("--min-efficiency", type=float, default=0.70, help="Minimum trajectory step efficiency (default: 0.70)")

    # Command: serve
    serve_parser = subparsers.add_parser("serve", help="Start the dynamic web dashboard server")
    serve_parser.add_argument("--port", "-p", type=int, default=8000, help="Port to listen on (default: 8000)")
    serve_parser.add_argument("--api-key", default=None, help="Default API key for evaluation ingestion server")
    serve_parser.add_argument("--model", default=None, help="Default LLM model identifier for server evaluation")
    serve_parser.add_argument("--base-url", default=None, help="OpenAI-compatible API base URL for server evaluation")
    serve_parser.add_argument("--llm-judge", action="store_true", help="Enable LLM judge by default for ingested traces")

    # Command: demo
    demo_parser = subparsers.add_parser("demo", help="Run evaluation on sample scenarios")
    demo_parser.add_argument("--file", default=None, help="Optional scenarios file path")
    demo_parser.add_argument("--api-key", default=None, help="API key for LLM judge")
    demo_parser.add_argument("--model", default=None, help="LLM judge model identifier")
    demo_parser.add_argument("--base-url", default=None, help="OpenAI-compatible API base URL")
    demo_parser.add_argument("--llm-judge", action="store_true", help="Enable LLM semantic reasoning judge")

    args = parser.parse_args()

    if args.command == "eval":
        run_eval_from_file(
            file_path=args.file,
            api_key=args.api_key,
            model=args.model,
            base_url=args.base_url,
            use_llm_judge=args.llm_judge,
            min_tool_selection=args.min_tool_selection,
            min_argument_correctness=args.min_arg_correctness,
            min_order_accuracy=args.min_order_accuracy,
            min_trajectory_efficiency=args.min_efficiency,
        )
    elif args.command == "serve":
        start_server_command(
            port=args.port,
            api_key=args.api_key,
            model=args.model,
            base_url=args.base_url,
            use_llm_judge=args.llm_judge,
        )
    elif args.command == "demo":
        sample_path = args.file or os.path.join(os.path.dirname(__file__), "..", "examples", "sample_scenarios.json")
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "agent_trajectories.json")
        run_eval_from_file(
            file_path=sample_path,
            api_key=args.api_key,
            model=args.model,
            base_url=args.base_url,
            use_llm_judge=args.llm_judge,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

