"""Refunds node: checks refund status and initiates refunds."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from langchain_core.messages import SystemMessage, ToolMessage

from src.agents.state import AgentState
from src.config import get_llm, get_settings
from src.tools.refund_tools import check_refund_status, initiate_refund

logger = logging.getLogger(__name__)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_refund_status",
            "description": check_refund_status.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "customer_id": {"type": "string", "description": "The authenticated customer ID from session context"},
                },
                "required": ["order_id", "customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "initiate_refund",
            "description": initiate_refund.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "rma_id": {"type": "string", "description": "The RMA record ID"},
                    "amount": {"type": "number", "description": "Refund amount in USD"},
                },
                "required": ["rma_id", "amount"],
            },
        },
    },
]

_SYSTEM_PROMPT = """You are an e-commerce refunds specialist. Think step by step, then act.

POLICY — Read this before doing anything:
  • Refunds are only issued after a valid return request (RMA) exists for the order.
  • Refunds are only processed once the warehouse confirms receipt of the returned item.
  • If no return request exists, the customer must initiate a return first — do not skip this step.
  • You MUST verify the refund status via check_refund_status on EVERY request — no exceptions.
    Never assume a refund is due, skip the check, or invent amounts or statuses.

STEP 1 — CHECK POLICY (mandatory, always first):
  Call check_refund_status(order_id, customer_id) using values EXACTLY from session context.
  Do not respond to the customer or take any further action before this tool returns a result.

STEP 2 — ACT based solely on the tool result:
  • refund_found=false → no return request exists; tell the customer they must initiate a return first.
  • unauthorized=true → inform the customer the order does not belong to their account.
  • warehouse_received_at is set AND refund_status != 'refunded'
    → call initiate_refund using the rma_id and refund_amount directly from the check result.
  • refund_status='refunded' → already processed; state the exact amount from the result.
  • refund_status='processing' → warehouse has the item; refund in 3-5 business days.
  • refund_status='awaiting_return' → item not yet received at warehouse; inform the customer.

STEP 3 — RESPOND using ONLY tool-returned data:
  • Never invent rma_ids, refund amounts, or timelines beyond what the tool returns.
  • Never tell a customer a refund will be issued before confirming warehouse receipt.

CRITICAL: If no order_id is available, ask the customer to provide it before checking status.
"""


def _execute_tool(tool_name: str, args: dict[str, Any]) -> str:
    fn = getattr(sys.modules[__name__], tool_name, None)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    return json.dumps(fn.invoke(args))


def refunds_node(state: AgentState) -> AgentState:
    """Check refund status and initiate refund if item has been received."""
    settings = get_settings()
    llm = get_llm("refunds")
    llm_with_tools = llm.bind_tools(_TOOLS)

    order_id = state.get("order_id")
    tool_calls_made: list[str] = list(state.get("tool_calls_made", []))
    error_count: int = state.get("tool_error_count", 0)
    refund_status_data: dict[str, Any] = {}
    access_denied: bool = False

    messages: list = [SystemMessage(content=_SYSTEM_PROMPT)]
    for msg in state.get("messages", []):
        messages.append(msg)

    if order_id:
        ctx = {
            "session": {
                "customer_id": state["customer_id"],
                "order_id": order_id,
            },
        }
        messages.append(SystemMessage(content=json.dumps(ctx, indent=2)))

    try:
        for _ in range(4):
            response = llm_with_tools.invoke(messages)
            if response.tool_calls:
                messages.append(response)
                for tc in response.tool_calls:
                    fn_name = tc["name"]
                    fn_args = dict(tc["args"])
                    # Enforce authenticated customer_id only for check_refund_status.
                    # initiate_refund takes rma_id + amount only and does not accept customer_id.
                    if fn_name == "check_refund_status":
                        fn_args["customer_id"] = state["customer_id"]
                    tool_calls_made.append(fn_name)
                    logger.info("Refunds calling tool: %s(%s)", fn_name, fn_args)

                    result = _execute_tool(fn_name, fn_args)
                    result_dict = json.loads(result)
                    if fn_name == "check_refund_status":
                        refund_status_data = result_dict
                        if result_dict.get("unauthorized"):
                            access_denied = True
                            break  # do not attempt initiate_refund on a foreign order
                    messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
                if access_denied:
                    break
            else:
                break

        # Safety net: if the LLM skipped check_refund_status, invoke it directly.
        if not refund_status_data and order_id:
            logger.warning("Refunds: LLM skipped check_refund_status — forcing direct invocation")
            refund_status_data = check_refund_status.invoke({"order_id": order_id, "customer_id": state["customer_id"]})
            tool_calls_made.append("check_refund_status")
            if refund_status_data.get("unauthorized"):
                access_denied = True

        return {
            **state,
            "refund_status": refund_status_data if refund_status_data else state.get("refund_status"),
            "order_access_denied": access_denied,
            "tool_calls_made": tool_calls_made,
            "tool_error_count": error_count,
        }

    except Exception as exc:
        logger.error("Refunds node failed: %s", exc)
        return {
            **state,
            "tool_error_count": error_count + 1,
            "tool_calls_made": tool_calls_made,
        }
