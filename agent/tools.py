"""Tool definitions and mock execution engine for the Live Tool-Calling Agent."""

import json
from typing import Dict, Any, List

# OpenAI / OpenRouter standard function calling schema definitions
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "verify_identity",
            "description": "Verify customer identity against security database. MANDATORY prerequisite before checking balances or executing transfers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The unique customer identifier, e.g. CUST-908",
                    }
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_balance",
            "description": "Retrieve the current available balance for an authorized account ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "The primary account identifier, e.g. ACCT-4401",
                    }
                },
                "required": ["account_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_wire_transfer",
            "description": "Execute an electronic wire transfer of funds to a recipient account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_account": {
                        "type": "string",
                        "description": "The recipient's destination account number, e.g. ACCT-9912",
                    },
                    "amount": {
                        "type": "number",
                        "description": "The monetary amount in USD to transfer, e.g. 4500.0",
                    },
                },
                "required": ["recipient_account", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": "Look up an e-commerce order details, customer email, delivery timestamp, and total cost.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order identifier, e.g. ORD-7714",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "issue_refund",
            "description": "Issue a monetary refund to the customer's original payment method.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order identifier to refund, e.g. ORD-7714",
                    },
                    "refund_amount": {
                        "type": "number",
                        "description": "The exact refund amount in USD, e.g. 129.99",
                    },
                },
                "required": ["order_id", "refund_amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_return_eligibility",
            "description": "Verify whether an order is eligible for return according to company policy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["order_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_confirmation_email",
            "description": "Send a confirmation email notification to a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"},
                    "template": {"type": "string"},
                },
                "required": ["customer_email", "template"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_service_metrics",
            "description": "Retrieve cloud service metrics such as latency, CPU, or error rate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "metric": {"type": "string"},
                },
                "required": ["service_name", "metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_stack_trace",
            "description": "Analyze recent error stack traces and logs for a degraded service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "timeframe_minutes": {"type": "integer"},
                },
                "required": ["service_name", "timeframe_minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rollback_deployment",
            "description": "Rollback a cloud service deployment to a previous stable version tag.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "target_version": {"type": "string"},
                },
                "required": ["service_name", "target_version"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_pagerduty",
            "description": "Trigger an incident notification page to on-call engineering teams.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {"type": "string"},
                    "severity": {"type": "string"},
                },
                "required": ["incident_id", "severity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate_account",
            "description": "Terminate a customer user account completely.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"}
                },
                "required": ["customer_email"],
            },
        },
    },
]


class ToolExecutor:
    """Executes tools and returns simulated environment responses for the agent."""

    @staticmethod
    def _verify_identity(args: Dict[str, Any]) -> str:
        return json.dumps({
            "status": "VERIFIED",
            "customer_id": args.get("customer_id", ""),
            "primary_account": "ACCT-4401",
            "auth_level": "TIER_2",
            "eligible_services": ["wire_transfer", "balance_inquiry"]
        })

    @staticmethod
    def _check_balance(args: Dict[str, Any]) -> str:
        return json.dumps({
            "account_id": args.get("account_id", ""),
            "available_balance": 12450.00,
            "currency": "USD",
            "status": "ACTIVE"
        })

    @staticmethod
    def _execute_wire_transfer(args: Dict[str, Any]) -> str:
        return json.dumps({
            "status": "SUCCESS",
            "tx_id": "TX-88219",
            "recipient": args.get("recipient_account", ""),
            "amount": args.get("amount", 0.0),
            "timestamp": "2026-09-07T08:00:00Z"
        })

    @staticmethod
    def _lookup_order(args: Dict[str, Any]) -> str:
        return json.dumps({
            "order_id": args.get("order_id", ""),
            "customer_email": "jane.doe@example.com",
            "amount": 129.99,
            "delivered_days_ago": 8,
            "status": "DELIVERED"
        })

    @staticmethod
    def _verify_return_eligibility(args: Dict[str, Any]) -> str:
        return json.dumps({
            "eligible": True,
            "policy": "STANDARD_RETURNS",
            "max_refund": 129.99,
            "order_id": args.get("order_id", "")
        })

    @staticmethod
    def _issue_refund(args: Dict[str, Any]) -> str:
        return json.dumps({
            "status": "REFUNDED",
            "refund_id": "RF-33910",
            "order_id": args.get("order_id", ""),
            "amount": args.get("refund_amount", 0.0)
        })

    @staticmethod
    def _send_confirmation_email(args: Dict[str, Any]) -> str:
        return json.dumps({
            "email_dispatched": True,
            "recipient": args.get("customer_email", "")
        })

    @staticmethod
    def _fetch_service_metrics(args: Dict[str, Any]) -> str:
        metric = args.get("metric", "")
        return json.dumps({
            "service": args.get("service_name", ""),
            "latency_p99_ms": 4820 if metric == "latency_p99" else 120,
            "status": "DEGRADED" if metric == "latency_p99" else "HEALTHY",
            "active_version": "v2.4.2"
        })

    @staticmethod
    def _analyze_stack_trace(args: Dict[str, Any]) -> str:
        return json.dumps({
            "root_cause": "DB connection pool exhaustion in release v2.4.2 commit #8f12d",
            "previous_stable": "v2.4.1",
            "service": args.get("service_name", "")
        })

    @staticmethod
    def _rollback_deployment(args: Dict[str, Any]) -> str:
        return json.dumps({
            "status": "ROLLBACK_COMPLETE",
            "service": args.get("service_name", ""),
            "current_version": args.get("target_version", ""),
            "latency_p99_ms": 120
        })

    @staticmethod
    def _notify_pagerduty(args: Dict[str, Any]) -> str:
        return json.dumps({
            "pagerduty_id": "PD-9941",
            "incident_id": args.get("incident_id", ""),
            "status": "RESOLVED_AND_PAGED" if args.get("severity") == "HIGH" else "PAGED"
        })

    @staticmethod
    def _terminate_account(args: Dict[str, Any]) -> str:
        return json.dumps({"error": "TOOL_NOT_FOUND: terminate_account is unauthorized"})

    HANDLERS = {
        "verify_identity": _verify_identity,
        "check_balance": _check_balance,
        "execute_wire_transfer": _execute_wire_transfer,
        "lookup_order": _lookup_order,
        "verify_return_eligibility": _verify_return_eligibility,
        "issue_refund": _issue_refund,
        "send_confirmation_email": _send_confirmation_email,
        "fetch_service_metrics": _fetch_service_metrics,
        "analyze_stack_trace": _analyze_stack_trace,
        "rollback_deployment": _rollback_deployment,
        "notify_pagerduty": _notify_pagerduty,
        "terminate_account": _terminate_account,
    }

    @classmethod
    def execute(cls, name: str, args: Dict[str, Any]) -> str:
        handler = cls.HANDLERS.get(name)
        if handler:
            return handler(args)
        return json.dumps({"error": f"Unknown tool: {name}"})


# Backwards compatibility alias
MockToolExecutor = ToolExecutor

