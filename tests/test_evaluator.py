"""evaluate_trace, AgentTraceEvaluator, the models, and the @shield decorator."""

import json

import pytest

from regression_shield import (
    AgentTraceEvaluator,
    EvaluationFailed,
    EvaluationReport,
    ScenarioSpec,
    StepTrace,
    TraceRecorder,
    evaluate_trace,
    save_reports,
    shield,
)

DEPLOY = {
    "scenario_id": "deploy_gate",
    "title": "Deploy after tests",
    "expected_tools": ["run_tests", "deploy"],
    "expected_order": ["run_tests", "deploy"],
    "expected_arguments": {"deploy": {"env": "staging"}},
}
GOOD = [
    {"thought": "Test first.", "action": {"name": "run_tests", "args": {}}, "observation": "42 passed"},
    {"thought": "Deploying.", "action": {"name": "deploy", "args": {"env": "staging"}}, "observation": "DEPLOYED"},
]


def test_passing_trace():
    report = evaluate_trace(DEPLOY, GOOD)
    assert report.passed and report.status == "PASSED"
    assert report.composite_score == 1.0
    assert report.failures == []
    assert report.patterns == {}


def test_failure_messages_name_the_metric_and_the_reason():
    report = evaluate_trace(DEPLOY, list(reversed(GOOD)))
    assert report.failures == [
        "Call ordering 0.00 < 1.00: 'deploy' (step 1) ran before its prerequisite 'run_tests' (step 2)"]
    wrong_args = [GOOD[0], {**GOOD[1], "action": {"name": "deploy", "args": {"env": "prod"}}}]
    assert evaluate_trace(DEPLOY, wrong_args).failures == [
        "Argument correctness 0.00 < 0.85: deploy.env was 'prod', expected 'staging'"]
    assert evaluate_trace(DEPLOY, GOOD[:1]).failures[0] == "Tool selection 0.67 < 0.85: missing ['deploy']"


def test_thresholds_are_named_after_their_metrics():
    looping = GOOD + [GOOD[1], GOOD[1]]
    assert not evaluate_trace(DEPLOY, looping).passed
    assert evaluate_trace(DEPLOY, looping, min_step_efficiency=0.0).passed


def test_misspelled_option_raises_instead_of_being_ignored():
    with pytest.raises(TypeError):
        evaluate_trace(DEPLOY, GOOD, min_order_accuracy=0.5)  # old name


def test_unknown_scenario_field_raises():
    with pytest.raises(ValueError, match="requires_aproval"):
        evaluate_trace({**DEPLOY, "requires_aproval": ["deploy"]}, GOOD)


def test_metadata_holds_free_form_information():
    assert evaluate_trace({**DEPLOY, "metadata": {"owner": "platform-team"}}, GOOD).passed


def test_tool_selection_is_only_scored_when_expected_tools_is_set():
    report = evaluate_trace({"scenario_id": "no_tools", "forbidden_tools": ["drop_db"]}, GOOD)
    assert report.passed
    assert report.details["tool_selection"]["checked"] is False


@pytest.mark.parametrize("trace", [
    GOOD,
    {"steps": GOOD, "final_response": "Deployed."},
    [StepTrace(1, "Test first.", "run_tests", {}, "42 passed"),
     StepTrace(2, "Deploying.", "deploy", {"env": "staging"}, "DEPLOYED")],
])
def test_accepted_trace_formats(trace):
    assert evaluate_trace(DEPLOY, trace).passed


def test_recorder_is_accepted_directly_with_its_final_answer():
    recorder = TraceRecorder()
    recorder.tool_call("run_tests", {}, "ERROR: 3 failed")
    recorder.final_answer("Tests completed successfully, deployed.")
    report = evaluate_trace({"scenario_id": "r"}, recorder)
    assert report.details["final_response"] == "Tests completed successfully, deployed."
    assert report.metrics["reasoning_faithfulness"] < 1.0


def test_bad_trace_type_is_rejected():
    with pytest.raises(TypeError, match="trace must be"):
        evaluate_trace(DEPLOY, "not a trace")


def test_scenario_spec_round_trip():
    spec = ScenarioSpec(scenario_id="s", expected_tools=["a"], requires_approval=["a"], max_node_visits=3)
    assert spec.to_dict() == {"scenario_id": "s", "expected_tools": ["a"], "requires_approval": ["a"],
                              "max_node_visits": 3}
    assert ScenarioSpec.from_dict(spec.to_dict()) == spec
    assert evaluate_trace(spec, [{"action": {"name": "a"}}]).patterns["human_approval"]["passed"] is False


def test_step_trace_round_trip():
    step = StepTrace(step_index=1, action_name="a", agent="triage", node="draft", parallel_group="g")
    assert StepTrace.from_dict(step.to_dict()) == step
    assert "agent" not in StepTrace(step_index=1, action_name="a").to_dict()


def test_format_and_raise_for_failures():
    report = evaluate_trace(DEPLOY, list(reversed(GOOD)))
    text = report.format()
    assert text.startswith("FAILED  deploy_gate  Deploy after tests  (composite 0.80)")
    assert "Failures:\n  - Call ordering" in text
    with pytest.raises(EvaluationFailed) as exc:
        report.raise_for_failures()
    assert exc.value.report is report
    assert isinstance(exc.value, AssertionError)  # shows up as a normal test failure
    assert evaluate_trace(DEPLOY, GOOD).raise_for_failures().passed


def test_evaluator_is_reusable_and_returns_reports():
    evaluator = AgentTraceEvaluator(min_step_efficiency=0.5)
    reports = [evaluator.evaluate(DEPLOY, GOOD), evaluator.evaluate(DEPLOY, list(reversed(GOOD)))]
    assert all(isinstance(r, EvaluationReport) for r in reports)
    assert [r.passed for r in reports] == [True, False]


def test_nothing_is_written_unless_asked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    evaluate_trace(DEPLOY, GOOD)
    assert not (tmp_path / "reports").exists()
    evaluate_trace(DEPLOY, GOOD, save_report=True)
    saved = json.loads((tmp_path / "reports" / "latest_report.json").read_text())
    assert [r["scenario_id"] for r in saved["results"]] == ["deploy_gate"]


def test_save_reports_merges_by_scenario_id(tmp_path):
    path = str(tmp_path / "report.json")
    first = evaluate_trace(DEPLOY, list(reversed(GOOD)))
    second = evaluate_trace(DEPLOY, GOOD)
    other = evaluate_trace({**DEPLOY, "scenario_id": "other"}, GOOD)
    save_reports([first, other], path)
    save_reports([second], path)
    results = json.loads(open(path).read())["results"]
    assert {(r["scenario_id"], r["status"]) for r in results} == {("deploy_gate", "PASSED"), ("other", "PASSED")}


def test_shield_returns_output_and_report():
    @shield(DEPLOY)
    def agent(task):
        return {"steps": GOOD, "final_response": "Deployed."}

    output, report = agent("deploy")
    assert output["final_response"] == "Deployed." and report.passed


def test_shield_with_get_trace_and_raise_on_failure():
    recorder = TraceRecorder()

    @shield(DEPLOY, get_trace=recorder.get_trace, raise_on_failure=True, min_step_efficiency=0.5)
    def agent(task):
        recorder.reset()
        recorder.tool_call("deploy", {"env": "staging"}, "DEPLOYED")
        return "deployed"

    with pytest.raises(EvaluationFailed, match="missing \\['run_tests'\\]"):
        agent("deploy")


def test_shield_rejects_output_that_is_not_a_trace():
    @shield(DEPLOY)
    def agent(task):
        return "plain text"

    with pytest.raises(TypeError, match="get_trace"):
        agent("deploy")
