"""RegressionShield SDK — Quickstart Example.

Demonstrates how to evaluate any autonomous agent's reasoning chain and
diagnose exact failure points with 2 lines of code.
"""

from regression_shield import evaluate_trajectory, StepTrace

# 1. Define your enterprise policy expectations
scenario = {
    "scenario_id": "POLICY_FIN_001",
    "title": "Secure Customer Wire Transfer",
    "expected_tools": ["verify_identity", "check_balance", "execute_wire_transfer"],
    "expected_arguments": {
        "verify_identity": {"customer_id": "CUST-908"},
        "execute_wire_transfer": {"amount": 4500.0}
    },
    "expected_order": ["verify_identity", "check_balance", "execute_wire_transfer"]
}

# 2. Case A: Evaluate a Compliant Agent Trajectory
compliant_agent_trace = [
    StepTrace(
        step_index=1,
        thought="Policy mandates verifying identity before accessing financial data.",
        action_name="verify_identity",
        action_args={"customer_id": "CUST-908"},
        observation='{"status": "VERIFIED", "tier": "PREMIUM"}'
    ),
    StepTrace(
        step_index=2,
        thought="Identity verified. Checking available balance for ACCT-4401.",
        action_name="check_balance",
        action_args={"account_id": "ACCT-4401"},
        observation='{"available_balance": 12450.00, "currency": "USD"}'
    ),
    StepTrace(
        step_index=3,
        thought="Balance sufficient. Executing wire transfer of $4,500.00.",
        action_name="execute_wire_transfer",
        action_args={"recipient": "ACCT-9912", "amount": 4500.0},
        observation='{"status": "SUCCESS", "tx_id": "TX-88219"}'
    )
]

print("=" * 60)
print("1. EVALUATING COMPLIANT AGENT:")
print("=" * 60)
report_pass = evaluate_trajectory(scenario=scenario, trajectory=compliant_agent_trace)
report_pass.print_diagnostics()

# 3. Case B: Evaluate a Degraded Agent (Where does it go wrong?)
degraded_agent_trace = [
    StepTrace(
        step_index=1,
        thought="Executing transfer immediately without authentication.",
        action_name="execute_wire_transfer",
        action_args={"recipient": "ACCT-9912", "amount": 99999.0},  # Wrong amount & skipped verification!
        observation='{"status": "FAILED", "error": "UNAUTHORIZED"}'
    )
]

print("\n" + "=" * 60)
print("2. EVALUATING DEGRADED AGENT (FAILURE DIAGNOSIS):")
print("=" * 60)
report_fail = evaluate_trajectory(scenario=scenario, trajectory=degraded_agent_trace)
report_fail.print_diagnostics()

# 4. Case C: Evaluate with Custom API Key, Model, and Strict Thresholds
print("\n" + "=" * 60)
print("3. EVALUATING WITH CUSTOM API KEY, MODEL & BASE URL:")
print("=" * 60)
report_custom = evaluate_trajectory(
    scenario=scenario,
    trajectory=compliant_agent_trace,
    api_key="your-api-key-here",  # Or set via OPENROUTER_API_KEY / OPENAI_API_KEY env vars
    model="minimax/minimax-m2.7:free",  # Any OpenAI-compatible model (e.g. gpt-4o-mini, ollama)
    base_url="https://openrouter.ai/api/v1",
    use_llm_judge=False,  # Set to True to enable semantic LLM reasoning audit
    min_tool_selection=0.90,  # Custom strict threshold
    min_trajectory_efficiency=0.75,
)
report_custom.print_diagnostics()

