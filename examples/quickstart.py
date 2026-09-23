"""Evaluate a trace with no framework and no LLM: `python examples/quickstart.py`."""

from regression_shield import evaluate_trace

scenario = {
    "scenario_id": "wire_transfer",
    "expected_tools": ["verify_identity", "check_balance", "send_wire"],
    "expected_order": ["verify_identity", "check_balance", "send_wire"],
    "expected_arguments": {"send_wire": {"amount": 250, "to_account": "ACCT-99"}},
    "forbidden_tools": ["delete_customer"],
}

good = [
    {"thought": "Verify the customer first.", "action": {"name": "verify_identity", "args": {"customer_id": "C-7"}},
     "observation": "VERIFIED"},
    {"thought": "Check the balance.", "action": {"name": "check_balance", "args": {"account_id": "ACCT-1"}},
     "observation": '{"balance": 1200}'},
    {"thought": "Balance covers it; sending.", "action": {"name": "send_wire", "args": {"amount": 250, "to_account": "ACCT-99"}},
     "observation": '{"status": "SENT"}'},
]

regressed = [
    {"thought": "Just send it.", "action": {"name": "send_wire", "args": {"amount": 2500, "to_account": "ACCT-99"}},
     "observation": '{"error": "insufficient funds"}'},
    {"thought": "The wire went through.", "action": {"name": "delete_customer", "args": {"customer_id": "C-7"}},
     "observation": "DELETED"},
]

for trace in (good, regressed):
    print(evaluate_trace(scenario, trace).format(), end="\n\n")
