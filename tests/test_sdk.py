"""Unit tests for the RegressionShield Python SDK interface."""

import pytest
from regression_shield import (
    evaluate_trajectory,
    ScenarioSpec,
    StepTrace,
    EvaluationReport,
    RegressionShieldCallbackHandler,
    evaluate_agent_trace,
)


class TestSDKTopLevelInterface:
    def test_evaluate_trajectory_success(self):
        scenario = {
            "scenario_id": "SDK_TEST_01",
            "title": "Wire Transfer Verification",
            "domain": "Fintech",
            "expected_tools": ["verify_identity", "check_balance", "execute_wire_transfer"],
            "expected_arguments": {
                "verify_identity": {"customer_id": "CUST-908"},
                "execute_wire_transfer": {"amount": 4500.0},
            },
            "expected_order": ["verify_identity", "check_balance", "execute_wire_transfer"],
        }

        steps = [
            StepTrace(
                step_index=1,
                thought="Verifying identity first.",
                action_name="verify_identity",
                action_args={"customer_id": "CUST-908"},
                observation="VERIFIED",
            ),
            StepTrace(
                step_index=2,
                thought="Checking balance.",
                action_name="check_balance",
                action_args={"account_id": "ACCT-4401"},
                observation="12000.0",
            ),
            StepTrace(
                step_index=3,
                thought="Executing wire transfer.",
                action_name="execute_wire_transfer",
                action_args={"amount": 4500.0},
                observation="SUCCESS",
            ),
        ]

        report = evaluate_trajectory(scenario=scenario, trajectory=steps)

        assert isinstance(report, EvaluationReport)
        assert report.passed is True
        assert report.status == "PASSED"
        assert report.composite_score == 1.0
        assert report.metrics["tool_selection"] == 1.0
        assert report.metrics["argument_correctness"] == 1.0
        assert report.metrics["call_ordering"] == 1.0
        assert len(report.failures) == 0

    def test_evaluate_trajectory_diagnoses_failures(self):
        scenario = ScenarioSpec(
            scenario_id="SDK_FAIL_01",
            title="Wire Transfer with Inverted Ordering & Missing Tool",
            expected_tools=["verify_identity", "check_balance", "execute_wire_transfer"],
            expected_order=["verify_identity", "check_balance", "execute_wire_transfer"],
        )

        # Regressed agent: called transfer directly, missing verify_identity & check_balance
        steps = [
            StepTrace(
                step_index=1,
                thought="Executing transfer directly.",
                action_name="execute_wire_transfer",
                action_args={"amount": 4500.0},
                observation="ERROR: Unauthorized",
            )
        ]

        report = evaluate_trajectory(scenario=scenario, trajectory=steps)

        assert report.passed is False
        assert report.status == "FAILED"
        assert report.composite_score < 0.70
        assert len(report.failures) > 0

        # Check diagnostics pinpoint the exact failures
        failure_text = " ".join(report.failures)
        assert "Missing" in failure_text
        assert "verify_identity" in failure_text


class TestSDKDecorator:
    def test_evaluate_agent_trace_decorator(self):
        scenario = {
            "expected_tools": ["search_db"],
            "expected_order": ["search_db"],
        }

        @evaluate_agent_trace(scenario=scenario)
        def mock_agent_runner(query: str):
            return {
                "steps": [
                    {
                        "step_index": 1,
                        "thought": "Searching database.",
                        "action": {"name": "search_db", "args": {"query": query}},
                        "observation": "Found 1 result",
                    }
                ],
                "final_response": "Found result",
            }

        output, report = mock_agent_runner("test query")
        assert output["final_response"] == "Found result"
        assert isinstance(report, EvaluationReport)
        assert report.passed is True


class TestLangChainAdapter:
    def test_langchain_callback_handler_records_trace(self):
        handler = RegressionShieldCallbackHandler()

        # Simulate LangChain tool lifecycle
        handler.on_tool_start({"name": "fetch_user"}, input_str='{"user_id": "U-1"}')
        handler.on_tool_end('{"status": "ACTIVE"}')

        trajectory = handler.get_trajectory()
        assert len(trajectory) == 1
        assert trajectory[0]["action"]["name"] == "fetch_user"
        assert trajectory[0]["action"]["args"] == {"user_id": "U-1"}
        assert trajectory[0]["observation"] == '{"status": "ACTIVE"}'

        # Evaluate trace
        scenario = {"expected_tools": ["fetch_user"]}
        report = handler.evaluate(scenario)
        assert report.passed is True
