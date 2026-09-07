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


class TestConfigurableParametersAndJudge:
    def test_evaluate_trajectory_custom_arguments(self):
        scenario = {
            "scenario_id": "SDK_PARAM_01",
            "title": "Custom Threshold & Model Scenario",
            "expected_tools": ["tool_a", "tool_b"],
        }
        steps = [
            StepTrace(
                step_index=1,
                thought="Using tool_a.",
                action_name="tool_a",
                action_args={},
                observation="OK",
            )
        ]

        # By default min_tool_selection is 0.85; tool_a only gives F1 = 0.67 -> fails default
        report_default = evaluate_trajectory(scenario=scenario, trajectory=steps)
        assert report_default.passed is False

        # With lowered threshold 0.50 -> passes!
        report_custom = evaluate_trajectory(
            scenario=scenario,
            trajectory=steps,
            api_key="sk-test-key",
            model="minimax/minimax-m2.7:free",
            base_url="https://openrouter.ai/api/v1",
            min_tool_selection=0.50,
        )
        assert report_custom.passed is True
        assert report_custom.metrics["tool_selection"] > 0.50

    def test_llm_judge_initialization_and_mock(self, monkeypatch):
        import httpx
        from regression_shield.core.llm_judge import LLMJudge

        judge = LLMJudge(
            api_key="sk-mock-key",
            model="minimax/minimax-m2.7:free",
            base_url="https://openrouter.ai/api/v1",
        )
        assert judge.model == "minimax/minimax-m2.7:free"
        assert judge.base_url == "https://openrouter.ai/api/v1"
        assert judge.api_key == "sk-mock-key"

        class MockResponse:
            status_code = 200
            def json(self):
                return {
                    "choices": [{
                        "message": {
                            "content": '```json\n{"passed": true, "score": 0.98, "reasoning": "Reasoning accurately mirrors observations."}\n```'
                        }
                    }]
                }
            @property
            def text(self):
                return ""

        monkeypatch.setattr(httpx.Client, "post", lambda self, *args, **kwargs: MockResponse())

        audit = judge.verify_reasoning_and_outcome(
            goal="Process refund",
            trajectory_steps=[{"thought": "Checking policy", "observation": "Eligible"}],
            final_response="Refund processed.",
        )

        assert audit["passed"] is True
        assert audit["score"] == 0.98
        assert "Reasoning accurately" in audit["reasoning"]
        assert audit["model"] == "minimax/minimax-m2.7:free"

    def test_top_level_llm_judge_integration_with_mock(self, monkeypatch):
        import httpx

        class MockResponse:
            status_code = 200
            def json(self):
                return {
                    "choices": [{
                        "message": {
                            "content": '{"passed": true, "score": 0.95, "reasoning": "All steps verified cleanly."}'
                        }
                    }]
                }
            @property
            def text(self):
                return ""

        monkeypatch.setattr(httpx.Client, "post", lambda self, *args, **kwargs: MockResponse())

        scenario = {
            "scenario_id": "SDK_JUDGE_01",
            "title": "Wire Transfer with Judge",
            "expected_tools": ["verify_id"],
        }
        steps = [
            StepTrace(
                step_index=1,
                thought="Checking user ID.",
                action_name="verify_id",
                action_args={"user_id": "U-123"},
                observation="VERIFIED",
            )
        ]

        report = evaluate_trajectory(
            scenario=scenario,
            trajectory=steps,
            api_key="sk-test",
            model="minimax/minimax-m2.7:free",
            use_llm_judge=True,
        )

        assert report.passed is True
        assert report.judge_audit is not None
        assert report.judge_audit["passed"] is True
        assert report.judge_audit["score"] == 0.95

    def test_cli_execution_with_model_argument(self, tmp_path, capsys):
        from regression_shield.cli import run_eval_from_file
        import json

        sample_file = tmp_path / "test_scenarios.json"
        sample_file.write_text(json.dumps([{
            "scenario": {
                "scenario_id": "CLI_TEST_01",
                "title": "CLI Test Scenario",
                "expected_tools": ["tool_x"]
            },
            "trajectory": [
                {
                    "step_index": 1,
                    "thought": "Invoking tool_x",
                    "action": {"type": "tool_call", "name": "tool_x", "args": {}},
                    "observation": "DONE"
                }
            ]
        }]), encoding="utf-8")

        run_eval_from_file(
            file_path=str(sample_file),
            model="minimax/minimax-m2.7:free",
            base_url="https://openrouter.ai/api/v1",
        )

        captured = capsys.readouterr().out
        assert "CLI_TEST_01" in captured
        assert "PASSED" in captured
        assert "minimax/minimax-m2.7:free" in captured

    def test_server_status_and_config(self):
        from regression_shield.server import _CONFIG, start_server
        assert "minimax/minimax-m2.7:free" in _CONFIG["model"]
        assert "https://openrouter.ai/api/v1" in _CONFIG["base_url"]


