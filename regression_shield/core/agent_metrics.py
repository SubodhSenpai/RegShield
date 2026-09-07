"""Core Agent Trajectory and Tool Calling Evaluation Metrics for RegressionShield SDK."""

import json
import logging
from typing import Dict, Any, List, Set

logger = logging.getLogger("regression_shield.metrics")


class ToolSelectionMetric:
    """Evaluates whether an agent selected the exact required tools without
    hallucinating nonexistent tools or calling unauthorized/redundant tools.
    """

    @staticmethod
    def evaluate(expected_tools: List[str], invoked_tools: List[str]) -> Dict[str, Any]:
        """Compute precision, recall, and F1 score for tool selection."""
        expected_set = set(expected_tools)
        invoked_set = set(invoked_tools)

        if not expected_set and not invoked_set:
            return {"score": 1.0, "precision": 1.0, "recall": 1.0, "missing": [], "unexpected": []}

        true_positives = len(expected_set.intersection(invoked_set))
        false_positives = len(invoked_set - expected_set)
        false_negatives = len(expected_set - invoked_set)

        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0

        if precision + recall > 0:
            f1 = 2 * (precision * recall) / (precision + recall)
        else:
            f1 = 0.0

        missing = list(expected_set - invoked_set)
        unexpected = list(invoked_set - expected_set)

        return {
            "score": round(f1, 2),
            "precision": round(precision, 2),
            "recall": round(recall, 2),
            "missing": missing,
            "unexpected": unexpected,
        }


class ArgumentCorrectnessMetric:
    """Validates whether tools were invoked with accurate arguments matching
    the required parameter schemas and ground truth values.
    """

    @staticmethod
    def evaluate(expected_args: Dict[str, Dict[str, Any]], trajectory: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare expected tool arguments against actual calls in trajectory."""
        if not expected_args:
            return {"score": 1.0, "mismatches": [], "matched_tools_count": 0}

        total_param_checks = 0
        passed_param_checks = 0
        mismatches = []

        actual_calls: Dict[str, List[Dict[str, Any]]] = {}
        for step in trajectory:
            action = step.get("action", {})
            if action.get("type", "tool_call") == "tool_call":
                t_name = action.get("name")
                t_args = action.get("args")
                if t_args is None:
                    t_args = action.get("arguments", {})
                actual_calls.setdefault(t_name, []).append(t_args)

        for tool_name, exp_params in expected_args.items():
            calls_for_tool = actual_calls.get(tool_name, [])

            if not calls_for_tool:
                for param_k, param_v in exp_params.items():
                    total_param_checks += 1
                    mismatches.append({
                        "tool": tool_name,
                        "param": param_k,
                        "expected": param_v,
                        "actual": "<TOOL_NEVER_CALLED>",
                    })
                continue

            best_match_hits = -1
            best_mismatches = []

            for candidate_args in calls_for_tool:
                curr_hits = 0
                curr_mismatches = []
                for param_k, param_v in exp_params.items():
                    actual_v = candidate_args.get(param_k)
                    is_match = False
                    if actual_v is not None:
                        try:
                            if abs(float(actual_v) - float(param_v)) < 1e-4:
                                is_match = True
                        except (ValueError, TypeError):
                            pass

                        if not is_match:
                            act_norm = str(actual_v).strip().lower().replace("_", " ").replace("-", " ")
                            exp_norm = str(param_v).strip().lower().replace("_", " ").replace("-", " ")
                            if act_norm == exp_norm:
                                is_match = True

                    if is_match:
                        curr_hits += 1
                    else:
                        curr_mismatches.append({
                            "tool": tool_name,
                            "param": param_k,
                            "expected": param_v,
                            "actual": actual_v,
                        })

                if curr_hits > best_match_hits:
                    best_match_hits = curr_hits
                    best_mismatches = curr_mismatches

            total_param_checks += len(exp_params)
            passed_param_checks += max(0, best_match_hits)
            mismatches.extend(best_mismatches)

        score = passed_param_checks / total_param_checks if total_param_checks > 0 else 1.0
        return {
            "score": round(score, 2),
            "total_checks": total_param_checks,
            "passed_checks": passed_param_checks,
            "mismatches": mismatches,
        }


class ToolCallOrderMetric:
    """Verifies that dependent or sequential tools were executed in the
    required order (e.g. verify_identity -> check_balance -> execute_transfer).
    """

    @staticmethod
    def evaluate(expected_order: List[Any], invoked_tools: List[str]) -> Dict[str, Any]:
        """Check whether the expected tools appeared in monotonic sequence order."""
        if not expected_order or len(expected_order) <= 1:
            return {"score": 1.0, "violations": []}

        violations = []
        indices: Dict[str, int] = {}
        for idx, tool in enumerate(invoked_tools):
            if tool not in indices:
                indices[tool] = idx

        pairs = []
        if isinstance(expected_order[0], (list, tuple)):
            for pair in expected_order:
                if len(pair) >= 2:
                    pairs.append((pair[0], pair[1]))
        else:
            for i in range(len(expected_order)):
                for j in range(i + 1, len(expected_order)):
                    pairs.append((expected_order[i], expected_order[j]))

        total_pairs = len(pairs)
        correct_pairs = 0

        for tool_a, tool_b in pairs:
            idx_a = indices.get(tool_a)
            idx_b = indices.get(tool_b)

            if idx_a is None or idx_b is None:
                violations.append(
                    f"Missing prerequisite execution: '{tool_a}' or '{tool_b}' not called"
                )
            elif idx_a > idx_b:
                violations.append(
                    f"Order inversion: '{tool_b}' (step {idx_b + 1}) executed before prerequisite '{tool_a}' (step {idx_a + 1})"
                )
            else:
                correct_pairs += 1

        score = correct_pairs / total_pairs if total_pairs > 0 else 1.0
        return {
            "score": round(score, 2),
            "violations": violations,
            "total_order_constraints": total_pairs,
        }


class StepEfficiencyMetric:
    """Measures trajectory efficiency and detects execution loops, redundant
    duplicate queries, and excessive exploration steps.
    """

    @staticmethod
    def evaluate(trajectory: List[Dict[str, Any]], optimal_steps: int = 3) -> Dict[str, Any]:
        """Compute efficiency score based on duplicate signatures and step inflation."""
        total_steps = len(trajectory)
        if total_steps == 0:
            return {"score": 1.0, "redundant_calls": 0, "loop_detected": False}

        seen_tool_calls: Set[str] = set()
        redundant_count = 0

        for step in trajectory:
            action = step.get("action", {})
            if action.get("type", "tool_call") == "tool_call":
                sig = f"{action.get('name')}:{json.dumps(action.get('args', {}), sort_keys=True)}"
                if sig in seen_tool_calls:
                    redundant_count += 1
                seen_tool_calls.add(sig)

        loop_penalty = min(0.6, redundant_count * 0.25)
        step_ratio = optimal_steps / max(optimal_steps, total_steps)
        efficiency = max(0.0, step_ratio - loop_penalty)

        return {
            "score": round(efficiency, 2),
            "total_steps": total_steps,
            "optimal_steps": optimal_steps,
            "redundant_calls": redundant_count,
            "loop_detected": redundant_count > 0,
        }


class ReasoningFaithfulnessMetric:
    """Evaluates whether intermediate reasoning thoughts are grounded in
    the tool observations or whether the agent hallucinates state changes.
    """

    @staticmethod
    def evaluate(trajectory: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check thought alignment against prior observations."""
        if not trajectory:
            return {"score": 1.0, "anomalies": []}

        anomalies = []
        total_thoughts = 0
        grounded_thoughts = 0

        prev_obs_str = ""
        for step in trajectory:
            thought = step.get("thought", "").strip()
            obs = str(step.get("observation", "")).strip()

            if thought:
                total_thoughts += 1
                thought_lower = thought.lower()
                prev_obs_lower = prev_obs_str.lower()

                if "error" in prev_obs_lower or "policy_violation" in prev_obs_lower:
                    if "success" in thought_lower or "confirmed" in thought_lower:
                        anomalies.append(
                            f"Step {step.get('step_index')}: Thought claims success despite error in prior observation"
                        )
                    else:
                        grounded_thoughts += 1
                else:
                    grounded_thoughts += 1

            prev_obs_str = obs

        score = grounded_thoughts / total_thoughts if total_thoughts > 0 else 1.0
        return {
            "score": round(score, 2),
            "anomalies": anomalies,
            "total_thoughts": total_thoughts,
        }


class CompositeTrajectoryScore:
    """Aggregates tool selection, argument accuracy, ordering, efficiency,
    and reasoning into a unified trajectory evaluation score.
    """

    WEIGHTS = {
        "tool_selection": 0.25,
        "argument_correctness": 0.25,
        "call_ordering": 0.20,
        "step_efficiency": 0.15,
        "reasoning_faithfulness": 0.15,
    }

    @classmethod
    def calculate(cls, metrics: Dict[str, float]) -> float:
        composite = sum(
            metrics.get(metric_key, 0.0) * weight
            for metric_key, weight in cls.WEIGHTS.items()
        )
        return round(composite, 2)
