"""smolagents: a CodeAgent (tools called from generated Python) and a manager with a sub-agent.

``instrument_smolagents`` records each tool call as it runs, and records the
manager calling its sub-agent as a handoff.

    pip install "regression-shield[smolagents]" "smolagents[openai]"
    python examples/09_smolagents.py
"""

from _llm import smolagents_model
from smolagents import CodeAgent, ToolCallingAgent, tool

from regression_shield import evaluate_trace, instrument_smolagents


@tool
def get_stock_price(ticker: str) -> float:
    """Latest price of a stock.

    Args:
        ticker: Stock ticker, e.g. AAPL.
    """
    return {"AAPL": 227.5, "MSFT": 431.2}.get(ticker.upper(), 0.0)


@tool
def convert_currency(amount: float, to_currency: str) -> float:
    """Convert US dollars to another currency.

    Args:
        amount: Amount in USD.
        to_currency: Target currency code, e.g. EUR.
    """
    return round(amount * {"EUR": 0.92, "GBP": 0.79}.get(to_currency.upper(), 1.0), 2)


CODE_SCENARIO = {
    "scenario_id": "stock_in_euros",
    "title": "CodeAgent calls both tools",
    "expected_tools": ["get_stock_price", "convert_currency"],
    "expected_order": ["get_stock_price", "convert_currency"],
    "expected_arguments": {"get_stock_price": {"ticker": "AAPL"}, "convert_currency": {"to_currency": "EUR"}},
}

MANAGER_SCENARIO = {
    "scenario_id": "delegated_quote",
    "title": "Manager delegates the lookup",
    # The conversion needs the price, so it can't be requested alongside the lookup
    "expected_order": ["get_stock_price", "convert_currency"],
    "expected_arguments": {"convert_currency": {"amount": 431.2, "to_currency": "GBP"}},
    "agent_tools": {"market_agent": ["get_stock_price"], "manager": ["convert_currency"]},
    "expected_agents": ["manager", "market_agent"],
}

if __name__ == "__main__":
    code_agent = CodeAgent(tools=[get_stock_price, convert_currency], model=smolagents_model(),
                           max_steps=4, verbosity_level=0)
    recorder = instrument_smolagents(code_agent)
    print("CodeAgent:", code_agent.run("What is Apple's (AAPL) stock price in euros?"))
    print(evaluate_trace(CODE_SCENARIO, recorder, save_report=True).format(), "\n")

    market = ToolCallingAgent(tools=[get_stock_price], model=smolagents_model(), name="market_agent",
                              description="Looks up stock prices.", max_steps=3, verbosity_level=0)
    manager = ToolCallingAgent(tools=[convert_currency], managed_agents=[market], model=smolagents_model(),
                               name="manager", max_steps=5, verbosity_level=0)
    recorder = instrument_smolagents(manager)
    print("Manager:", manager.run("Ask market_agent for Microsoft's (MSFT) price, then convert it to GBP."))
    report = evaluate_trace(MANAGER_SCENARIO, recorder, save_report=True)
    print(report.format())
    print("agents:", report.patterns.get("multi_agent", {}).get("details", {}).get("agents"))
