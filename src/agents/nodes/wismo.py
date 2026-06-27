"""WISMO node: resolves 'Where Is My Order' queries using order tools."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from langchain_core.messages import SystemMessage, ToolMessage

from src.agents.state import AgentState
from src.config import get_llm, get_settings
from src.tools.order_tools import get_carrier_tracking, get_customer_orders, get_order_details, get_order_status

logger = logging.getLogger(__name__)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_customer_orders",
            "description": get_customer_orders.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "The authenticated customer ID from session context"},
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": get_order_status.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID (e.g. ORD-1042)"},
                    "customer_id": {"type": "string", "description": "The authenticated customer ID from session context"},
                },
                "required": ["order_id", "customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_details",
            "description": get_order_details.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID"},
                    "customer_id": {"type": "string", "description": "The authenticated customer ID from session context"},
                },
                "required": ["order_id", "customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_carrier_tracking",
            "description": get_carrier_tracking.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID"},
                    "customer_id": {"type": "string", "description": "The authenticated customer ID from session context"},
                },
                "required": ["order_id", "customer_id"],
            },
        },
    },
]

_SYSTEM_PROMPT = """You are an e-commerce order tracking assistant. Think step by step, then act.

STEP 1 — REASON: Read the session context and decide:
  • Specific order_id provided? → call get_order_status then get_order_details.
  • Customer asks for detailed live tracking? → also call get_carrier_tracking.
  • No order_id, customer asks about their orders or history? → call get_customer_orders.
  You MUST call at least one tool. Do not reply before calling a tool.

STEP 2 — ACT: Call the tool(s).
  • Use customer_id EXACTLY from the session context — never use an ID from the user's message.
  • For a specific order: call get_order_status first, then get_order_details.
  • If the customer asks "where exactly is my package" or "live tracking" — also call get_carrier_tracking.
  • For order history: call get_customer_orders.

STEP 3 — VERIFY the result:
  • success=true → use ONLY the returned data; never invent or add any field.
  • unauthorized=true → the order does not belong to this customer; do not reveal any details.
  • error present → inform the customer there was a problem retrieving their order.

CRITICAL: Never fabricate tracking numbers, carriers, amounts, item names, or dates.
Every fact in your reply must come directly from a tool result in this conversation.
"""


def _execute_tool(tool_name: str, tool_args: dict[str, Any]) -> str:
    tool_fn = getattr(sys.modules[__name__], tool_name, None)
    if not tool_fn:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    result = tool_fn.invoke(tool_args)
    return json.dumps(result)


def wismo_node(state: AgentState) -> AgentState:
    """Fetch order status/details and prepare data for the responder."""
    settings = get_settings()
    llm = get_llm("wismo")
    llm_with_tools = llm.bind_tools(_TOOLS)

    order_id = state.get("order_id")
    tool_calls_made: list[str] = list(state.get("tool_calls_made", []))
    error_count: int = state.get("tool_error_count", 0)
    order_data: dict[str, Any] = {}
    orders_list: list[dict[str, Any]] = []
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
    else:
        ctx = {
            "session": {
                "customer_id": state["customer_id"],
                "order_id": None,
            },
        }
    messages.append(SystemMessage(content=json.dumps(ctx, indent=2)))

    try:
        for _ in range(3):
            response = llm_with_tools.invoke(messages)
            if response.tool_calls:
                messages.append(response)
                for tc in response.tool_calls:
                    fn_name = tc["name"]
                    fn_args = dict(tc["args"])
                    # Always enforce the authenticated session customer_id.
                    # This prevents the LLM from using a customer_id supplied
                    # by the user's message (cross-customer data access).
                    fn_args["customer_id"] = state["customer_id"]
                    tool_calls_made.append(fn_name)
                    logger.info("WISMO calling tool: %s(%s)", fn_name, fn_args)

                    tool_result = _execute_tool(fn_name, fn_args)
                    result_dict = json.loads(tool_result)
                    if result_dict.get("unauthorized"):
                        access_denied = True
                    if fn_name == "get_order_details" and result_dict.get("success"):
                        order_data = result_dict
                    if fn_name == "get_carrier_tracking" and result_dict.get("success"):
                        # Merge tracking enrichment into order_data
                        order_data.update({
                            "latest_event": result_dict.get("latest_event"),
                            "current_location": result_dict.get("current_location"),
                            "tracking_url": result_dict.get("tracking_url"),
                            "tracking_events": result_dict.get("events"),
                        })
                    if fn_name == "get_customer_orders" and result_dict.get("success"):
                        orders_list = result_dict.get("orders", [])

                    messages.append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))
            else:
                break

        # Safety net: if the LLM skipped all tool calls, invoke the required tool directly.
        if not order_data and not orders_list and not access_denied:
            logger.warning("WISMO: LLM skipped tool calls — forcing direct invocation")
            if order_id:
                raw = get_order_details.invoke({"order_id": order_id, "customer_id": state["customer_id"]})
                if raw.get("unauthorized"):
                    access_denied = True
                elif raw.get("success"):
                    order_data = raw
                    tool_calls_made.append("get_order_details")
            else:
                raw = get_customer_orders.invoke({"customer_id": state["customer_id"]})
                if raw.get("success"):
                    orders_list = raw.get("orders", [])
                    tool_calls_made.append("get_customer_orders")

        return {
            **state,
            "order_data": order_data if order_data else state.get("order_data"),
            "orders_list": orders_list if orders_list else state.get("orders_list", []),
            "order_access_denied": access_denied,
            "tool_calls_made": tool_calls_made,
            "tool_error_count": error_count,
        }

    except Exception as exc:
        logger.error("WISMO node failed: %s", exc)
        return {
            **state,
            "tool_error_count": error_count + 1,
            "tool_calls_made": tool_calls_made,
        }
