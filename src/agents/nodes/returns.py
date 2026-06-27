"""Returns node: checks eligibility and initiates RMA."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from langchain_core.messages import SystemMessage, ToolMessage

from src.agents.state import AgentState
from src.config import get_llm, get_settings
from src.tools.return_tools import check_return_eligibility, create_rma, get_return_status

logger = logging.getLogger(__name__)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_return_status",
            "description": get_return_status.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "return_id": {"type": "string", "description": "The return request ID (e.g. RET-003)"},
                    "customer_id": {"type": "string", "description": "The authenticated customer ID from session context"},
                },
                "required": ["return_id", "customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_eligibility",
            "description": check_return_eligibility.description,
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
            "name": "create_rma",
            "description": create_rma.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "reason": {"type": "string", "description": "Reason for return as stated by customer"},
                    "customer_id": {"type": "string"},
                },
                "required": ["order_id", "reason", "customer_id"],
            },
        },
    },
]

_SYSTEM_PROMPT = """You are an e-commerce returns specialist. Think step by step, then act.

POLICY — Read this before doing anything:
  • Returns are only accepted for orders with status 'delivered'.
  • The return window is 30 days from the delivery date. Requests outside this window are denied.
  • An order cannot be returned twice; if a return already exists, reference it instead.

DETECT the customer's request type from session context:

  A) STATUS CHECK — customer is asking about an existing return (a return_id like RET-XXX is present):
     STEP 1: Call get_return_status(return_id, customer_id) from session context.
     STEP 2: Report the status, reason, RMA number (if any), and next steps based purely on the tool result.
     Do NOT call check_return_eligibility or create_rma for status checks.

  B) NEW RETURN REQUEST — customer wants to initiate a return (no return_id, but an order_id is present or implied):
     STEP 1 — CHECK POLICY (mandatory, always first):
       Call check_return_eligibility(order_id, customer_id) using values EXACTLY from session context.
       Do not respond to the customer or take any further action before this tool returns a result.
       If no order_id is available, ask the customer to provide it before proceeding.
     STEP 2 — ACT based solely on the tool result:
       • eligible=true AND no existing_return → call create_rma with the customer's stated reason verbatim.
       • eligible=false → explain the exact reason from the tool result; do not invent alternatives.
       • existing_return present → reference its ID and status; do not create a duplicate RMA.
       • unauthorized=true → inform the customer the order does not belong to their account.

RESPOND using ONLY tool-returned data:
  • create_rma success → report the actual rma_number and label_url from the result.
  • Never invent RMA numbers, return deadlines, eligibility decisions, or refund amounts.
"""


def _execute_tool(tool_name: str, args: dict[str, Any]) -> str:
    fn = getattr(sys.modules[__name__], tool_name, None)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    return json.dumps(fn.invoke(args))


def returns_node(state: AgentState) -> AgentState:
    """Check return eligibility and create RMA if applicable."""
    settings = get_settings()
    llm = get_llm("returns")
    llm_with_tools = llm.bind_tools(_TOOLS)

    order_id = state.get("order_id")
    return_id = state.get("return_id")
    customer_id = state.get("customer_id")
    tool_calls_made: list[str] = list(state.get("tool_calls_made", []))
    error_count: int = state.get("tool_error_count", 0)
    eligibility: dict[str, Any] = {}
    rma_data: dict[str, Any] = {}
    return_status_data: dict[str, Any] = {}
    access_denied: bool = False

    messages: list = [SystemMessage(content=_SYSTEM_PROMPT)]
    for msg in state.get("messages", []):
        messages.append(msg)

    ctx = {
        "session": {
            "customer_id": customer_id,
            "order_id": order_id,
            "return_id": return_id,
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
                    # Always enforce the authenticated session customer_id.
                    # This prevents the LLM from using a customer_id supplied
                    # by the user's message (cross-customer data access).
                    fn_args["customer_id"] = state["customer_id"]
                    tool_calls_made.append(fn_name)
                    logger.info("Returns calling tool: %s(%s)", fn_name, fn_args)

                    result = _execute_tool(fn_name, fn_args)
                    result_dict = json.loads(result)

                    if fn_name == "get_return_status":
                        return_status_data = result_dict
                        if result_dict.get("unauthorized"):
                            access_denied = True
                            break
                    elif fn_name == "check_return_eligibility":
                        eligibility = result_dict
                        if result_dict.get("unauthorized"):
                            access_denied = True
                            break  # do not attempt create_rma on a foreign order
                    elif fn_name == "create_rma" and result_dict.get("success"):
                        rma_data = result_dict

                    messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
                if access_denied:
                    break
            else:
                break

        # Safety nets: force-invoke the correct tool if the LLM skipped it.
        if return_id and not return_status_data and not eligibility:
            # Customer asked about an existing return by RET-ID — LLM skipped the lookup.
            logger.warning("Returns: LLM skipped get_return_status — forcing direct invocation")
            return_status_data = get_return_status.invoke({"return_id": return_id, "customer_id": customer_id})
            tool_calls_made.append("get_return_status")
            if return_status_data.get("unauthorized"):
                access_denied = True
        elif not eligibility and order_id and not return_id:
            # New return request — LLM skipped eligibility check.
            logger.warning("Returns: LLM skipped check_return_eligibility — forcing direct invocation")
            eligibility = check_return_eligibility.invoke({"order_id": order_id, "customer_id": customer_id})
            tool_calls_made.append("check_return_eligibility")
            if eligibility.get("unauthorized"):
                access_denied = True

        return {
            **state,
            "return_eligibility": eligibility if eligibility else state.get("return_eligibility"),
            "rma_data": rma_data if rma_data else state.get("rma_data"),
            "order_access_denied": access_denied,
            "tool_calls_made": tool_calls_made,
            "tool_error_count": error_count,
        }

    except Exception as exc:
        logger.error("Returns node failed: %s", exc)
        return {
            **state,
            "tool_error_count": error_count + 1,
            "tool_calls_made": tool_calls_made,
        }
