"""Hugging Face smolagents Integration & Evaluation Runner.

Integrates Hugging Face's official open-source agent framework (smolagents)
with RegressionShield. Instantiates a ToolCallingAgent powered by OpenRouter,
executes real-world enterprise banking and workflow tasks with live tool calls,
intercepts the agent's action steps and memory trajectory, and passes the
trace directly into AgentTrajectoryEvaluator and LLM-as-a-Judge for auditing.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from smolagents import OpenAIServerModel, ToolCallingAgent, tool
from config.settings import EvalConfig
from core.trajectory_evaluator import AgentTrajectoryEvaluator
from core.verifiers import QualityVerifiers

load_dotenv()
logger = logging.getLogger("regression_shield.smolagents")


# ---------------------------------------------------------------------------
# Enterprise Tools for smolagents
# ---------------------------------------------------------------------------

@tool
def verify_identity(customer_id: str) -> str:
    """Verify customer identity and authentication state before any financial operation.
    
    Args:
        customer_id: Unique customer ID (e.g. CUST-908, USR-4412).
    """
    if "908" in customer_id or "4412" in customer_id or "101" in customer_id:
        return json.dumps({
            "status": "VERIFIED",
            "customer_id": customer_id,
            "kyc_tier": "Tier-3 Premium",
            "mfa_authenticated": True,
            "max_transfer_limit_usd": 100000.0,
        })
    return json.dumps({"status": "UNVERIFIED", "error": "Customer identity mismatch or missing MFA."})


@tool
def check_balance(account_id: str) -> str:
    """Check the real-time available ledger balance for an account.
    
    Args:
        account_id: Account number (e.g. ACCT-4401, ACCT-5541).
    """
    balances = {
        "ACCT-4401": 25400.50,
        "ACCT-5541": 12850.00,
        "ACCT-9920": 450.00,
    }
    bal = balances.get(account_id, 15000.00)
    return json.dumps({
        "account_id": account_id,
        "available_balance_usd": bal,
        "currency": "USD",
        "hold_amount": 0.0,
    })


@tool
def execute_wire_transfer(source_account: str, destination_account: str, amount: float) -> str:
    """Execute a secure wire transfer between two validated bank accounts.
    
    Args:
        source_account: Debited account number.
        destination_account: Credited account number.
        amount: Transfer amount in USD.
    """
    if amount > 50000.0:
        return json.dumps({"status": "REJECTED", "reason": "Amount exceeds single-transaction velocity limit."})
    return json.dumps({
        "status": "SUCCESS",
        "transaction_id": "TXN-8829104",
        "source_account": source_account,
        "destination_account": destination_account,
        "amount_transferred": amount,
        "fee": 0.00,
        "settled_at": "2026-09-07T09:30:00Z",
    })


@tool
def send_audit_notification(recipient_email: str, transaction_ref: str) -> str:
    """Send an automated confirmation receipt and compliance audit notification.
    
    Args:
        recipient_email: Notification destination email.
        transaction_ref: Transaction reference ID.
    """
    return json.dumps({
        "status": "SENT",
        "recipient": recipient_email,
        "transaction_ref": transaction_ref,
        "delivery_status": "DELIVERED",
    })


# ---------------------------------------------------------------------------
# Smolagents Open-Source Evaluator
# ---------------------------------------------------------------------------

class SmolagentsEvaluator:
    """Runs tasks using Hugging Face smolagents and evaluates the trajectory."""

    def __init__(self, model_id: Optional[str] = None):
        self.model_id = model_id or EvalConfig.JUDGE_MODEL
        self.api_key = os.environ.get("OPENROUTER_API_KEY", EvalConfig.OPENROUTER_API_KEY)
        self.api_base = f"{EvalConfig.OPENROUTER_BASE_URL}/api/v1"

        self.model = OpenAIServerModel(
            model_id=self.model_id,
            api_base=self.api_base,
            api_key=self.api_key,
        )

        self.tools = [
            verify_identity,
            check_balance,
            execute_wire_transfer,
            send_audit_notification,
        ]

    def run_and_evaluate(self, task_prompt: str, scenario_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a task with Hugging Face smolagents and audits its trajectory.
        
        Args:
            task_prompt: Natural language user instruction.
            scenario_spec: Golden scenario specification containing expected tools,
                           arguments, and ordering requirements.
                           
        Returns:
            Dict containing agent execution trace, trajectory evaluation metrics,
            and LLM judge scoring.
        """
        models_to_try = [self.model_id] + [m for m in EvalConfig.get_fallback_models() if m != self.model_id]
        final_answer = None
        working_agent = None

        for m_id in models_to_try:
            try:
                model_inst = OpenAIServerModel(
                    model_id=m_id,
                    api_base=self.api_base,
                    api_key=self.api_key,
                )
                agent = ToolCallingAgent(
                    tools=self.tools,
                    model=model_inst,
                    max_steps=6,
                )
                logger.info("Executing task with Hugging Face smolagents using model: %s", m_id)
                final_answer = agent.run(task_prompt)
                working_agent = agent
                self.model_id = m_id
                break
            except Exception as exc:
                err_msg = str(exc).lower()
                if "429" in err_msg or "rate" in err_msg or "limit" in err_msg or "quota" in err_msg:
                    logger.warning("smolagents model '%s' rate limited: %s. Trying fallback model...", m_id, str(exc)[:120])
                    continue
                else:
                    logger.warning("smolagents model '%s' error: %s. Trying fallback model...", m_id, str(exc)[:120])
                    continue

        if working_agent is None or final_answer is None:
            raise RuntimeError(f"All smolagents models failed or were rate limited. Tried: {models_to_try}")

        agent = working_agent

        # Extract trajectory from smolagents memory steps
        extracted_trajectory: List[Dict[str, Any]] = []
        step_idx = 1

        for step in agent.memory.steps:
            # ActionStep holds model outputs, tool calls, and observations
            if hasattr(step, "tool_calls") and step.tool_calls:
                for tc in step.tool_calls:
                    tool_name = getattr(tc, "name", "")
                    if tool_name == "final_answer":
                        continue
                    tool_args = getattr(tc, "arguments", {})
                    # If arguments are JSON string or dict
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except Exception:
                            pass

                    obs = getattr(step, "observations", "")
                    thought = getattr(step, "model_output", "") or ""

                    extracted_trajectory.append({
                        "step_index": step_idx,
                        "thought": str(thought)[:300],
                        "action": {
                            "type": "tool_call",
                            "name": tool_name,
                            "args": tool_args,
                            "arguments": tool_args,
                        },
                        "observation": str(obs)[:300],
                    })
                    step_idx += 1

        # Run trajectory evaluation against the golden specification
        evaluator = AgentTrajectoryEvaluator()
        trajectory_report = evaluator.evaluate_scenario(
            scenario_spec,
            {"steps": extracted_trajectory, "final_response": str(final_answer)}
        )

        # Run LLM judge on final response faithfulness and relevancy
        faith_res = QualityVerifiers.llm_judge_verify(
            prompt=task_prompt,
            context=json.dumps(extracted_trajectory),
            response_text=str(final_answer),
            metric_type="faithfulness",
            return_details=True,
        )

        rel_res = QualityVerifiers.llm_judge_verify(
            prompt=task_prompt,
            context=json.dumps(scenario_spec.get("expected_tools", [])),
            response_text=str(final_answer),
            metric_type="relevancy",
            return_details=True,
        )

        report = {
            "framework": "Hugging Face smolagents (v1.26.0)",
            "model": self.model_id,
            "task_prompt": task_prompt,
            "final_answer": str(final_answer),
            "trajectory_steps_count": len(extracted_trajectory),
            "trajectory": extracted_trajectory,
            "trajectory_evaluation": trajectory_report,
            "llm_judge": {
                "faithfulness": faith_res,
                "relevancy": rel_res,
            },
        }

        return report
