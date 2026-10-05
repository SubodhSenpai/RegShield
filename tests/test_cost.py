"""Cost tracking: model prices, usage records, budgets, and usage captured by the integrations."""

from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
import pytest

from regression_shield import RegressionShieldCallbackHandler, TraceRecorder, evaluate_trace
from regression_shield.core.cost import price_for, summarize_cost, validate_pricing
from regression_shield.recorder import usage_from_response


@pytest.fixture(autouse=True)
def no_config(monkeypatch):
    monkeypatch.setenv("REGSHIELD_CONFIG", "")  # ignore any config file around the test run


def call(name, args=None, observation="ok", **extra):
    return {"action": {"type": "tool_call", "name": name, "args": args or {}}, "observation": observation, **extra}


# -- prices -----------------------------------------------------------------------------

@pytest.mark.parametrize("model, key", [
    ("gpt-4o-mini", "gpt-4o-mini"),
    ("gpt-4o-mini-2024-07-18", "gpt-4o-mini-2024-07-18"),  # dated snapshots have their own entry
    ("openai/gpt-4o-mini", "gpt-4o-mini"),                 # OpenRouter-style provider prefix
    ("claude-sonnet-4-5", "claude-sonnet-4-5"),
    ("mistral-large-latest", "mistral/mistral-large-latest"),  # bare name, provider-prefixed entry
    ("llama3", "ollama/llama3"),
])
def test_snapshot_prices(model, key):
    price = price_for(model)
    assert price is not None and price.key == key and price.source == "snapshot"


def test_unknown_models_have_no_price():
    assert price_for("my-company-model") is None
    assert price_for("phi4") is None  # without a tag it could be local or hosted: you decide
    assert price_for("") is None


@pytest.mark.parametrize("model", [
    "qwen2.5-16k:3b", "llama3.1:8b-instruct-q4_K_M", "gemma3:latest", "gemma3n:e2b", "smollm2:135m",
    "deepseek-r1:7b",  # not the hosted 671B DeepSeek-R1's price
    "ollama_chat/phi4", "lm_studio/qwen2.5-7b-instruct", "hosted_vllm/my-model",
])
def test_local_models_are_free(model):
    price = price_for(model)
    assert (price.source, price.key, price.cost(1_000_000, 1_000_000)) == ("local", "local model", 0.0)


@pytest.mark.parametrize("model, key", [
    ("anthropic.claude-3-5-sonnet-20240620-v1:0", "anthropic.claude-3-5-sonnet-20240620-v1:0"),  # Bedrock ":0"
    ("ft:gpt-4o-mini-2024-07-18:acme::9xyz", "ft:gpt-4o-mini-2024-07-18"),                     # a fine-tune
])
def test_colon_names_that_are_not_local(model, key):
    assert price_for(model).key == key and price_for(model).input > 0


def test_ollama_cloud_models_are_not_local():
    from regression_shield.core.cost import is_local_model

    assert not is_local_model("gpt-oss:120b-cloud")  # runs on Ollama's servers
    assert is_local_model("gpt-oss:20b")


def test_openrouter_free_variants_are_free():
    price = price_for("meta-llama/llama-3.1-8b-instruct:free")
    assert (price.input, price.output, price.key) == (0.0, 0.0, ":free variant")


def test_your_pricing_wins_and_supports_wildcards():
    pricing = validate_pricing({"models": {"gpt-4o-mini": {"input": 1, "output": 2},
                                           "qwen*": {"input": 3, "output": 15}}})
    assert price_for("gpt-4o-mini", pricing).input == 1
    local = price_for("qwen2.5-16k:3b", pricing)  # a local model priced like the API it stands in for
    assert (local.key, local.source, local.cost(1_000_000, 1_000_000)) == ("qwen*", "pricing", 18.0)


def test_cost_formula_with_cached_and_written_tokens():
    price = price_for("claude-sonnet-4-5")  # $3 in, $15 out, $0.30 cache read, $3.75 cache write per 1M
    assert price.cost(1_000_000, 0) == pytest.approx(3.0)
    assert price.cost(0, 1_000_000) == pytest.approx(15.0)
    # 1M input: 600k cached, 100k written, 300k plain
    assert price.cost(1_000_000, 0, cached_input_tokens=600_000, cache_write_tokens=100_000) == pytest.approx(
        0.3 * 3.0 + 0.6 * 0.30 + 0.1 * 3.75)


@pytest.mark.parametrize("pricing, message", [
    ({"model": {}}, "pricing must be"),
    ({"models": {"x": {"input": 1}}}, "needs 'input' and 'output'"),
    ({"models": {"x": {"input": 1, "output": 1, "per_call": 2}}}, "unknown field"),
    ({"models": {"x": {"input": -1, "output": 1}}}, ">= 0"),
    ({"tools": {"search": "cheap"}}, "USD per call"),
])
def test_bad_pricing_is_rejected(pricing, message):
    with pytest.raises(ValueError, match=message):
        validate_pricing(pricing)


# -- usage and cost of a run ------------------------------------------------------------

def test_cost_summary_of_llm_calls_and_paid_tools():
    steps = [call("web_search", {"q": "refund policy"}, "...", cost_usd=0.005), call("lookup", {}, "ok")]
    calls = [{"model": "gpt-4o-mini", "input_tokens": 1_000_000, "output_tokens": 100_000},
             {"model": "gpt-4o-mini", "prompt_tokens": 1000, "completion_tokens": 10},  # OpenAI field names work too
             {"model": "my-local-model", "input_tokens": 500, "output_tokens": 50}]
    cost = summarize_cost(steps, calls, {"models": {}, "tools": {"lookup": 0.001}})
    assert cost["llm_calls"] == 3 and cost["total_tokens"] == 1_101_560
    assert cost["models"]["gpt-4o-mini"]["usd"] == pytest.approx(0.15 + 0.06 + 0.00015 + 0.000006)
    assert cost["tools"] == {"web_search": {"calls": 1, "usd": 0.005}, "lookup": {"calls": 1, "usd": 0.001}}
    assert cost["unpriced_models"] == ["my-local-model"] and cost["complete"] is False


def test_a_recorded_cost_is_used_as_is():
    cost = summarize_cost([], [{"model": "anything", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0123}])
    assert cost["total_usd"] == 0.0123 and cost["models"]["anything"]["price_source"] == "trace"


def test_no_usage_means_no_cost():
    assert summarize_cost([call("lookup")], []) is None
    assert evaluate_trace({"scenario_id": "s"}, [call("lookup")]).cost is None


def test_the_report_shows_the_cost():
    trace = {"steps": [call("lookup")], "final_response": "Found it.",
             "llm_calls": [{"model": "gpt-4o", "input_tokens": 12_000, "output_tokens": 800}]}
    report = evaluate_trace({"scenario_id": "s"}, trace)
    assert report.cost["total_usd"] == pytest.approx(0.038)
    assert "  cost: $0.0380 (1 LLM call, 12,800 tokens)" in report.format()


# -- budgets ----------------------------------------------------------------------------

LOOPING = {"steps": [call("get_job_status", {"job_id": "J-9"}, "PENDING")] * 5,
           "llm_calls": [{"model": "gpt-4o", "input_tokens": 9000, "output_tokens": 300}] * 6}


def test_budget_failures():
    report = evaluate_trace({"scenario_id": "export", "max_cost_usd": 0.10, "max_tokens": 40_000,
                             "max_llm_calls": 5}, LOOPING, min_step_efficiency=0)
    assert report.patterns["budget"]["violations"] == [
        "Cost $0.1530 is over the $0.1000 budget (gpt-4o $0.1530)",
        "55,800 tokens (max 40,000)",
        "6 LLM calls (max 5)",
    ]
    assert "Budget: Cost $0.1530 is over the $0.1000 budget" in report.failures[0]


def test_budget_within_limits():
    report = evaluate_trace({"scenario_id": "export", "max_cost_usd": 1, "max_llm_calls": 6}, LOOPING,
                            min_step_efficiency=0)
    assert report.passed and report.patterns["budget"]["details"]["llm_calls"] == 6


def test_a_budget_cant_pass_without_usage_or_prices():
    no_usage = evaluate_trace({"scenario_id": "s", "max_cost_usd": 1, "max_tokens": 10}, [call("lookup")])
    assert no_usage.patterns["budget"]["violations"] == [
        "No usage was recorded (LLM calls or paid tool calls), so the cost can't be checked",
        "No LLM calls were recorded, so the token and call budgets can't be checked"]
    unpriced = evaluate_trace({"scenario_id": "s", "max_cost_usd": 1},
                              {"steps": [], "llm_calls": [{"model": "my-model", "input_tokens": 5}]})
    assert unpriced.patterns["budget"]["violations"] == ["Cost unknown: no price for 'my-model'; add it to your pricing"]
    priced = evaluate_trace({"scenario_id": "s", "max_cost_usd": 1},
                            {"steps": [], "llm_calls": [{"model": "my-model", "input_tokens": 5}]},
                            pricing={"models": {"my-*": {"input": 0, "output": 0}}})
    assert priced.passed


def test_a_zero_budget_is_a_real_limit():
    report = evaluate_trace({"scenario_id": "s", "max_llm_calls": 0}, LOOPING)
    assert report.patterns["budget"]["violations"] == ["6 LLM calls (max 0)"]


# -- recording usage --------------------------------------------------------------------

def test_recorder_records_usage_apart_from_steps():
    recorder = TraceRecorder(agent="support")
    recorder.llm_call("gpt-4o-mini", 1200, 80, cached_input_tokens=1024)
    recorder.tool_call("web_search", {"q": "x"}, "results", cost_usd=0.005)
    assert [s["step_index"] for s in recorder.get_trace()] == [1]  # usage never shifts step numbers
    assert recorder.llm_calls == [{"model": "gpt-4o-mini", "input_tokens": 1200, "output_tokens": 80,
                                   "cached_input_tokens": 1024, "agent": "support"}]
    exported = recorder.to_dict()
    assert exported["llm_calls"] == recorder.llm_calls and exported["steps"][0]["cost_usd"] == 0.005
    report = evaluate_trace({"scenario_id": "s"}, recorder)
    assert report.cost["tools"]["web_search"]["usd"] == 0.005 and report.cost["llm_calls"] == 1
    recorder.reset()
    assert recorder.llm_calls == []


def test_wrapped_paid_tools_record_their_price():
    recorder = TraceRecorder()

    @recorder.tool(cost_usd=0.01)
    def send_sms(to: str) -> str:
        if not to:
            raise ValueError("no number")
        return "queued"

    send_sms("+15550100")
    with pytest.raises(ValueError):
        send_sms("")
    assert [s.get("cost_usd") for s in recorder.get_trace()] == [0.01, None]  # failed calls aren't charged


@pytest.mark.parametrize("response, usage", [
    # OpenAI chat completion
    (NS(model="gpt-4o-mini-2024-07-18", usage=NS(prompt_tokens=1200, completion_tokens=80,
                                                 prompt_tokens_details=NS(cached_tokens=1024))),
     {"model": "gpt-4o-mini-2024-07-18", "input_tokens": 1200, "output_tokens": 80, "cached_input_tokens": 1024}),
    # Anthropic message: input_tokens excludes the cache, so they're added back
    (NS(model="claude-sonnet-4-5", usage=NS(input_tokens=200, output_tokens=50, cache_read_input_tokens=1000,
                                            cache_creation_input_tokens=300)),
     {"model": "claude-sonnet-4-5", "input_tokens": 1500, "output_tokens": 50, "cached_input_tokens": 1000,
      "cache_write_tokens": 300}),
    # Gemini
    (NS(model_version="gemini-2.5-flash", usage_metadata=NS(prompt_token_count=900, candidates_token_count=40,
                                                            thoughts_token_count=10, cached_content_token_count=0)),
     {"model": "gemini-2.5-flash", "input_tokens": 900, "output_tokens": 50}),
    # A LangChain message
    (NS(usage_metadata={"input_tokens": 10, "output_tokens": 5, "input_token_details": {"cache_read": 4}},
        response_metadata={"model_name": "gpt-4o"}),
     {"model": "gpt-4o", "input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 4}),
    # OpenRouter reports the cost
    ({"model": "openai/gpt-4o-mini", "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.00042}},
     {"model": "openai/gpt-4o-mini", "input_tokens": 10, "output_tokens": 2, "cost_usd": 0.00042}),
])
def test_usage_from_provider_responses(response, usage):
    assert usage_from_response(response) == usage


def test_llm_response_records_or_ignores():
    recorder = TraceRecorder()
    assert recorder.llm_response(NS(model="x")) is None  # no usage, nothing recorded
    recorder.llm_response(NS(model="gpt-4o", usage=NS(prompt_tokens=5, completion_tokens=1)), model="override")
    assert recorder.llm_calls == [{"model": "override", "input_tokens": 5, "output_tokens": 1}]


# -- usage captured by the integrations -------------------------------------------------

def test_langchain_handler_records_model_usage():
    handler = RegressionShieldCallbackHandler()
    run_id = uuid4()
    handler.on_chat_model_start({}, [[]], run_id=run_id, metadata={},
                                invocation_params={"model": "gpt-4o-mini"})
    message = NS(usage_metadata={"input_tokens": 1500, "output_tokens": 60},
                 response_metadata={"model_name": "gpt-4o-mini-2024-07-18",
                                    "token_usage": {"prompt_tokens": 1500, "completion_tokens": 60, "cost": 0.0003}})
    handler.on_llm_end(NS(generations=[[NS(text="Looking it up.", message=message)]], llm_output={}), run_id=run_id)
    assert handler.llm_calls == [{"model": "gpt-4o-mini-2024-07-18", "input_tokens": 1500, "output_tokens": 60,
                                  "cost_usd": 0.0003}]
    assert handler.get_trace() == []  # usage doesn't add steps


def test_langchain_handler_falls_back_to_the_requested_model_name():
    handler = RegressionShieldCallbackHandler()
    run_id = uuid4()
    handler.on_llm_start({}, ["prompt"], run_id=run_id, metadata={"ls_model_name": "my-llm"})
    handler.on_llm_end(NS(generations=[[NS(text="hi")]],
                          llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}}), run_id=run_id)
    assert handler.llm_calls == [{"model": "my-llm", "input_tokens": 7, "output_tokens": 3}]


def test_langchain_real_agent_usage(monkeypatch):
    agents = pytest.importorskip("langchain.agents")
    messages = pytest.importorskip("langchain_core.messages")
    fake = pytest.importorskip("langchain_core.language_models.fake_chat_models")
    tools = pytest.importorskip("langchain_core.tools")

    class UsageModel(fake.GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    @tools.tool
    def lookup(order_id: str) -> str:
        """Look up an order."""
        return "delivered"

    usage = {"input_tokens": 300, "output_tokens": 20, "total_tokens": 320}
    model = UsageModel(messages=iter([
        messages.AIMessage(content="", usage_metadata=usage,
                           tool_calls=[{"name": "lookup", "args": {"order_id": "A-1"}, "id": "c1", "type": "tool_call"}]),
        messages.AIMessage(content="It was delivered.", usage_metadata=usage),
    ]))
    handler = RegressionShieldCallbackHandler()
    agents.create_agent(model, tools=[lookup]).invoke({"messages": [{"role": "user", "content": "Where is A-1?"}]},
                                                      config={"callbacks": [handler]})
    assert [c["input_tokens"] for c in handler.llm_calls] == [300, 300]
    report = evaluate_trace({"scenario_id": "s", "max_llm_calls": 2}, handler)
    assert report.passed and report.cost["total_tokens"] == 640


def test_smolagents_records_step_usage():
    smolagents = pytest.importorskip("smolagents")
    from smolagents.models import ChatMessage, MessageRole, Model
    from smolagents.monitoring import TokenUsage

    from regression_shield import instrument_smolagents

    class ScriptedModel(Model):
        def __init__(self, replies):
            super().__init__(model_id="scripted-model")
            self.replies = list(replies)

        def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kwargs):
            return ChatMessage(role=MessageRole.ASSISTANT, content=self.replies.pop(0),
                               token_usage=TokenUsage(input_tokens=400, output_tokens=25))

    tool = smolagents.tool

    @tool
    def lookup(order_id: str) -> str:
        """Look up an order.

        Args:
            order_id: The order id.
        """
        return "delivered"

    code = "Thought: look it up.\n<code>\nstatus = lookup(order_id='A-1')\nfinal_answer(status)\n</code>"
    agent = smolagents.CodeAgent(tools=[lookup], model=ScriptedModel([code]), max_steps=2, verbosity_level=0)
    recorder = instrument_smolagents(agent)
    agent.run("Where is A-1?")
    assert recorder.llm_calls == [{"model": "scripted-model", "input_tokens": 400, "output_tokens": 25}]


# -- the LLM judge's own cost -----------------------------------------------------------

def test_judge_reports_its_usage_and_cost(monkeypatch):
    for var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENROUTER_BASE_URL", "OPENAI_BASE_URL", "JUDGE_MODEL"):
        monkeypatch.delenv(var, raising=False)

    class Reply:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"score": 0.9, "reasoning": "ok"}'}}],
                    "usage": {"prompt_tokens": 2000, "completion_tokens": 50}}

    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kwargs: Reply())
    report = evaluate_trace({"scenario_id": "s"}, [call("lookup")], use_llm_judge=True, api_key="sk-test",
                            model="gpt-4o-mini", base_url="https://judge.example/v1")
    assert report.judge_audit["usage"] == {"input_tokens": 2000, "output_tokens": 50}
    assert report.judge_audit["cost_usd"] == pytest.approx(2000 * 0.15e-6 + 50 * 0.6e-6)
