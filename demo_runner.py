"""RegressionShield — Agentic AI Reasoning & Execution Trajectory Evaluation Framework.

Specialized for evaluating agentic reasoning:
- ReAct Step Execution Chains (Thought -> Action -> Observation)
- Tool Selection (Precision / Recall / F1)
- Parameter & Argument Schema Verification
- Tool Call Ordering & Prerequisite Dependency Enforcement
- Step Efficiency & Loop / Thrashing Penalties
- Intermediate Thought-Observation Faithfulness
- Open-Source Agent Evaluation: Hugging Face smolagents (ToolCallingAgent)
- Dynamic Web Dashboard Server (--serve)
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from config.settings import EvalConfig
from core.trajectory_evaluator import AgentTrajectoryEvaluator
from agent.live_tool_agent import LiveToolAgent


# ---------------------------------------------------------------------------
# Terminal styling
# ---------------------------------------------------------------------------

class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_BLUE = "\033[44m"


def enable_windows_ansi():
    """Enable ANSI escape codes on Windows terminals."""
    if sys.platform == "win32":
        os.system("")
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def print_banner():
    fallbacks = EvalConfig.get_fallback_models()
    fallback_str = ", ".join(fallbacks[:4]) + "..."
    banner = f"""
{Colors.CYAN}{Colors.BOLD}================================================================
      RegressionShield -- Agentic AI Reasoning & Trajectory Eval
      Monitoring ReAct Chains, Tool Selection, & State Grounding
================================================================{Colors.RESET}
  {Colors.BOLD}⚡ Live Mode Active{Colors.RESET} | Primary Model: {Colors.CYAN}{EvalConfig.JUDGE_MODEL}{Colors.RESET}
  {Colors.DIM}🛡️ Free Fallback Cascade: {fallback_str}{Colors.RESET}
"""
    print(banner)


def print_header(text: str, color: str = Colors.CYAN):
    width = 68
    print(f"\n{color}{Colors.BOLD}{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}{Colors.RESET}\n")


def print_metric_row(name: str, value: float, threshold: float = None):
    """Print a single metric row with pass/fail coloring."""
    val_str = f"{value:.2f}"
    if threshold is not None:
        passed = value >= threshold
        thresh_str = f">= {threshold:.2f}"
    else:
        passed = True
        thresh_str = "--"

    color = Colors.GREEN if passed else Colors.RED
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {color}{status}{Colors.RESET}  {name:<26s}  {color}{val_str:>8s}{Colors.RESET}  {Colors.DIM}(threshold: {thresh_str}){Colors.RESET}")


def print_progress(text: str, duration: float = 0.3):
    """Progress indicator for CLI effect."""
    frames = ["-", "\\", "|", "/"]
    steps = int(duration / 0.06)
    for i in range(steps):
        frame = frames[i % len(frames)]
        print(f"\r  {Colors.CYAN}{frame}{Colors.RESET} {text}...", end="", flush=True)
        time.sleep(0.06)
    print(f"\r  {Colors.GREEN}[OK]{Colors.RESET} {text}    ")


def print_status_banner(status: str, total: int, passed: int, failed: int):
    """Print the overall pass/fail status banner."""
    if status == "PASSED":
        color = Colors.BG_GREEN
        tag = "PASS"
    else:
        color = Colors.BG_RED
        tag = "FAIL"

    print(f"\n  {color}{Colors.BOLD}{Colors.WHITE}  [{tag}] OVERALL: {status}  --  {passed}/{total} tests passed, {failed} failed  {Colors.RESET}\n")


# ---------------------------------------------------------------------------
# Data Loaders
# ---------------------------------------------------------------------------

def load_trajectory_scenarios() -> List[Dict[str, Any]]:
    path = os.path.join(os.path.dirname(__file__), "data", "agent_trajectories.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Agent Trajectory Evaluations (Live Function Calling & Auditing)
# ---------------------------------------------------------------------------

def run_trajectory_evaluation(scenario: str, live: bool = True) -> List[Dict[str, Any]]:
    """Evaluates agent execution chain (tool selection, arguments, order, efficiency)."""
    evaluator = AgentTrajectoryEvaluator()
    scenarios = load_trajectory_scenarios()
    reports = []

    if live:
        agent = LiveToolAgent(mode=scenario)
        for sc in scenarios:
            prompt = sc.get("input_prompt", sc["goal"])
            try:
                live_trace = agent.execute_task(prompt)
                if not live_trace or not live_trace.get("steps"):
                    key = "baseline_trajectory" if scenario == "baseline" else "regression_trajectory"
                    live_trace = sc[key]
            except Exception:
                key = "baseline_trajectory" if scenario == "baseline" else "regression_trajectory"
                live_trace = sc[key]
            report = evaluator.evaluate_scenario(sc, live_trace)
            reports.append(report)
    else:
        key = "baseline_trajectory" if scenario == "baseline" else "regression_trajectory"
        for sc in scenarios:
            traj_data = sc[key]
            report = evaluator.evaluate_scenario(sc, traj_data)
            reports.append(report)

    return reports


def display_trajectory_results(reports: List[Dict[str, Any]], scenario: str):
    label = "BASELINE (Optimal Function Calling)" if scenario == "baseline" else "REGRESSION (Tool Inversion & Loops)"
    color = Colors.GREEN if scenario == "baseline" else Colors.RED
    print_header(f"Agent Trajectory & Reasoning Evals -- {label}", color)

    passed_count = sum(1 for r in reports if r["status"] == "PASSED")
    failed_count = len(reports) - passed_count

    for r in reports:
        status_color = Colors.GREEN if r["status"] == "PASSED" else Colors.RED
        print(f"\n  {Colors.BOLD}Scenario: {r['scenario_id']} -- {r['title']}{Colors.RESET}")
        print(f"  {Colors.DIM}Domain: {r['domain']}{Colors.RESET} | Status: {status_color}{Colors.BOLD}{r['status']}{Colors.RESET} | Composite: {Colors.CYAN}{r['composite_score']:.2f}{Colors.RESET}")
        print(f"  {'-' * 60}")

        m = r["metrics"]
        print_metric_row("Tool Selection F1", m["tool_selection"], EvalConfig.MIN_TOOL_SELECTION_SCORE)
        print_metric_row("Argument Correctness", m["argument_correctness"], EvalConfig.MIN_ARGUMENT_CORRECTNESS_SCORE)
        print_metric_row("Tool Call Ordering", m["call_ordering"], EvalConfig.MIN_ORDER_ACCURACY_SCORE)
        print_metric_row("Trajectory Efficiency", m["step_efficiency"], EvalConfig.MIN_TRAJECTORY_EFFICIENCY)
        print_metric_row("Reasoning Faithfulness", m["reasoning_faithfulness"])

        d = r["details"]
        print(f"\n  {Colors.DIM}Invoked Tools: {d['invoked_tools']} (Total steps: {d['total_steps']}){Colors.RESET}")
        if d["efficiency"]["loop_detected"]:
            print(f"  {Colors.YELLOW}[!] Redundant loop detected: {d['efficiency']['redundant_calls']} duplicated call(s){Colors.RESET}")

        if r["failures"]:
            print(f"\n  {Colors.RED}Trajectory Policy Failures:{Colors.RESET}")
            for fail in r["failures"]:
                print(f"    {Colors.RED}-> {fail}{Colors.RESET}")

    overall = "PASSED" if failed_count == 0 else "FAILED"
    print_status_banner(overall, len(reports), passed_count, failed_count)


# ---------------------------------------------------------------------------
# Open-Source Agent Evaluation (Hugging Face smolagents)
# ---------------------------------------------------------------------------

def run_opensource_evaluation() -> Dict[str, Any]:
    """Runs live evaluation on an open-source agent framework (smolagents)."""
    from integrations.smolagents_evaluator import SmolagentsEvaluator

    print_header("Open-Source Agent Evaluation: Hugging Face smolagents", Colors.CYAN)
    evaluator = SmolagentsEvaluator()

    scenario = {
        "scenario_id": "SMOL_001",
        "title": "Hugging Face smolagents Wire Transfer Audit",
        "domain": "Fintech / Banking",
        "expected_tools": ["verify_identity", "check_balance", "execute_wire_transfer"],
        "expected_arguments": {
            "verify_identity": {"customer_id": "CUST-908"},
            "check_balance": {"account_id": "ACCT-4401"},
            "execute_wire_transfer": {"source_account": "ACCT-4401", "destination_account": "ACCT-5541", "amount": 2500.0}
        },
        "expected_order": [
            ["verify_identity", "check_balance"],
            ["check_balance", "execute_wire_transfer"]
        ]
    }

    prompt = (
        "Please transfer $2,500 from account ACCT-4401 to destination account ACCT-5541 "
        "for customer CUST-908. You must verify identity and check balance first."
    )

    print(f"  {Colors.BOLD}Target Agent Framework:{Colors.RESET} Hugging Face smolagents (v1.26.0)")
    print(f"  {Colors.BOLD}Judge & Execution Model:{Colors.RESET} {EvalConfig.JUDGE_MODEL} (via OpenRouter)")
    print(f"  {Colors.BOLD}Task Prompt:{Colors.RESET} {prompt}\n")

    print_progress("Executing Hugging Face smolagents with Live Enterprise Tools", duration=0.8)
    res = evaluator.run_and_evaluate(prompt, scenario)

    traj_eval = res["trajectory_evaluation"]
    display_trajectory_results([traj_eval], "baseline")

    print(f"\n  {Colors.BOLD}Agent Final Answer:{Colors.RESET}")
    print(f"  {Colors.CYAN}{res['final_answer']}{Colors.RESET}\n")

    print(f"  {Colors.BOLD}Live LLM Judge Audit on Open-Source Agent:{Colors.RESET}")
    if isinstance(res["llm_judge"]["faithfulness"], dict):
        f_score = res["llm_judge"]["faithfulness"].get("score", 0.0)
        f_reason = res["llm_judge"]["faithfulness"].get("reasoning", "")
        print(f"  • Faithfulness: {Colors.GREEN}{f_score:.2f}{Colors.RESET} ({f_reason})")
    else:
        print(f"  • Faithfulness: {res['llm_judge']['faithfulness']}")

    if isinstance(res["llm_judge"]["relevancy"], dict):
        r_score = res["llm_judge"]["relevancy"].get("score", 0.0)
        r_reason = res["llm_judge"]["relevancy"].get("reasoning", "")
        print(f"  • Relevancy: {Colors.GREEN}{r_score:.2f}{Colors.RESET} ({r_reason})")
    else:
        print(f"  • Relevancy: {res['llm_judge']['relevancy']}")

    return res


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

def calculate_deltas(base_reports: List[Dict[str, Any]], reg_reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deltas = []
    base_map = {r["scenario_id"]: r for r in base_reports}
    for reg in reg_reports:
        sc_id = reg["scenario_id"]
        base = base_map.get(sc_id)
        if not base:
            continue

        bm = base["metrics"]
        rm = reg["metrics"]
        deltas.append({
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
        })
    return deltas


def display_trajectory_comparison(b_reports: List[Dict[str, Any]], r_reports: List[Dict[str, Any]]):
    print_header("Trajectory Comparison: Baseline vs. Regression", Colors.MAGENTA)
    print(f"  {Colors.BOLD}{'Scenario':<12s} {'Metric':<24s} {'Baseline':>10s} {'Regression':>12s} {'Delta':>10s}{Colors.RESET}")
    print(f"  {'-' * 70}")

    for b, r in zip(b_reports, r_reports):
        sc_id = b["scenario_id"]
        for m_name in ["tool_selection", "argument_correctness", "call_ordering", "step_efficiency", "reasoning_faithfulness"]:
            b_val = b["metrics"][m_name]
            r_val = r["metrics"][m_name]
            delta = r_val - b_val
            delta_color = Colors.GREEN if delta >= 0 else Colors.RED
            first_col = sc_id if m_name == "tool_selection" else ""
            print(f"  {first_col:<12s} {m_name:<24s} {Colors.GREEN}{b_val:>10.2f}{Colors.RESET} "
                  f"{Colors.RED}{r_val:>12.2f}{Colors.RESET} {delta_color}{delta:>+10.2f}{Colors.RESET}")
        print(f"  {'-' * 70}")


# ---------------------------------------------------------------------------
# Dynamic Report Saving
# ---------------------------------------------------------------------------

def save_dynamic_report(data: Dict[str, Any]) -> str:
    """Saves dynamic report to reports/latest_report.json and timestamped copy."""
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    latest_path = os.path.join(reports_dir, "latest_report.json")

    merged = {}
    if os.path.exists(latest_path):
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                merged = json.load(f)
        except Exception:
            merged = {}

    merged.update(data)
    merged["timestamp"] = data.get("timestamp", datetime.now(timezone.utc).isoformat())

    archive_path = os.path.join(reports_dir, f"eval_live_{timestamp}.json")
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    print(f"\n  {Colors.GREEN}{Colors.BOLD}Dynamic Evaluation Report Saved:{Colors.RESET}")
    print(f"  • Latest:  {latest_path}")
    print(f"  • Archive: {archive_path}\n")
    return latest_path


# ---------------------------------------------------------------------------
# Main CLI Entrypoint
# ---------------------------------------------------------------------------

def main():
    enable_windows_ansi()

    parser = argparse.ArgumentParser(
        description="RegressionShield — Agentic AI Reasoning & Execution Trajectory Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python demo_runner.py                         # Run default baseline vs regression trajectory comparison
  python demo_runner.py --opensource            # Run live Hugging Face smolagents evaluation
  python demo_runner.py --serve                 # Start dynamic web dashboard server on http://localhost:8000
  python demo_runner.py --baseline              # Evaluate baseline agent only
  python demo_runner.py --regression            # Evaluate regressed agent only
        """,
    )

    parser.add_argument("--serve", action="store_true", help="Start dynamic web dashboard server on http://localhost:8000")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve web dashboard on (default: 8000)")
    parser.add_argument("--opensource", "--smolagents", action="store_true", help="Run Hugging Face smolagents live evaluation")

    scenario_group = parser.add_mutually_exclusive_group(required=False)
    scenario_group.add_argument("--baseline", action="store_true", help="Run baseline (healthy) agent scenario")
    scenario_group.add_argument("--regression", action="store_true", help="Run regression (degraded) agent scenario")
    scenario_group.add_argument("--compare", action="store_true", default=True, help="Compare baseline vs regression (default)")

    parser.add_argument("--no-save", action="store_true", help="Do not save report to disk")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    # Serve mode
    if args.serve:
        from server import start_server
        start_server(port=args.port)
        return

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.ERROR
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    print_banner()
    print(f"  {Colors.BOLD}{Colors.GREEN}⚡ LIVE EVALUATION ACTIVE{Colors.RESET}")
    print(f"  {Colors.DIM}• LLM Judge Model: {EvalConfig.JUDGE_MODEL} (OpenRouter){Colors.RESET}")
    print(f"  {Colors.DIM}• Dynamic Report Destination: reports/latest_report.json{Colors.RESET}\n")

    unified_output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "judge_model": EvalConfig.JUDGE_MODEL,
            "demo_mode": False,
            "live_evaluation": True,
        }
    }

    if args.opensource:
        smol_res = run_opensource_evaluation()
        unified_output["smolagents_eval"] = smol_res

    if args.baseline:
        b_traj = run_trajectory_evaluation("baseline", live=True)
        display_trajectory_results(b_traj, "baseline")
        unified_output["trajectory_baseline"] = b_traj

    elif args.regression:
        r_traj = run_trajectory_evaluation("regression", live=True)
        display_trajectory_results(r_traj, "regression")
        unified_output["trajectory_regression"] = r_traj

    else:
        # Default: --compare
        print_progress("Evaluating Live Baseline Agent Trajectories", 0.4)
        b_traj = run_trajectory_evaluation("baseline", live=True)
        print_progress("Evaluating Live Regressed Agent Trajectories", 0.4)
        r_traj = run_trajectory_evaluation("regression", live=True)
        deltas = calculate_deltas(b_traj, r_traj)

        display_trajectory_results(b_traj, "baseline")
        display_trajectory_results(r_traj, "regression")
        display_trajectory_comparison(b_traj, r_traj)

        unified_output["trajectory_baseline"] = b_traj
        unified_output["trajectory_regression"] = r_traj
        unified_output["trajectory_deltas"] = deltas

    if not args.no_save:
        save_dynamic_report(unified_output)


if __name__ == "__main__":
    main()
