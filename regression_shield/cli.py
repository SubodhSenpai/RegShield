"""Command-Line Interface for RegressionShield SDK (regshield CLI)."""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Any

from regression_shield import evaluate_trajectory, AgentTrajectoryEvaluator


def run_eval_from_file(file_path: str):
    """Evaluate scenarios and trajectories provided in a JSON file."""
    if not os.path.exists(file_path):
        print(f"[!] Error: File not found: {file_path}")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else [data]
    evaluator = AgentTrajectoryEvaluator()

    print(f"\n[*] Evaluating {len(items)} Agent Trajectory Scenarios from {file_path}...\n")
    passed_count = 0

    for item in items:
        scenario = item.get("scenario") or item
        trajectory = item.get("trajectory") or item.get("steps") or item.get("baseline_trajectory")
        report = evaluator.evaluate_scenario(scenario, trajectory)

        status_tag = "[PASS]" if report["status"] == "PASSED" else "[FAIL]"
        print(f"{status_tag} [{report['status']}] {report['scenario_id']}: {report['title']} (Composite: {report['composite_score']:.2f})")
        
        if report["failures"]:
            for fail in report["failures"]:
                print(f"    -> {fail}")
        else:
            passed_count += 1
        print()

    print(f"Overall Result: {passed_count}/{len(items)} scenarios passed.\n")


def start_server_command(port: int = 8000):
    """Start the dynamic dashboard server."""
    from regression_shield.server import start_server
    start_server(port=port)


def main():
    parser = argparse.ArgumentParser(
        prog="regshield",
        description="RegressionShield — Agentic AI Reasoning & Trajectory Evaluation CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: eval
    eval_parser = subparsers.add_parser("eval", help="Evaluate agent trajectories from a JSON file")
    eval_parser.add_argument("--file", "-f", required=True, help="Path to JSON file containing scenarios & trajectories")

    # Command: serve
    serve_parser = subparsers.add_parser("serve", help="Start the dynamic web dashboard server")
    serve_parser.add_argument("--port", "-p", type=int, default=8000, help="Port to listen on (default: 8000)")

    # Command: demo
    demo_parser = subparsers.add_parser("demo", help="Run evaluation on sample scenarios")
    demo_parser.add_argument("--file", default=None, help="Optional scenarios file path")

    args = parser.parse_args()

    if args.command == "eval":
        run_eval_from_file(args.file)
    elif args.command == "serve":
        start_server_command(port=args.port)
    elif args.command == "demo":
        sample_path = args.file or os.path.join(os.path.dirname(__file__), "..", "examples", "sample_scenarios.json")
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "agent_trajectories.json")
        run_eval_from_file(sample_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
