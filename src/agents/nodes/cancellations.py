"""Cancellations node: handles order cancellation requests."""
from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.state import AgentState
from src.config import get_llm
from src.tools.notification_tools import send_customer_notification
from src.tools.order_tools import cancel_order

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """ROLE: You are an e-commerce customer support specialist handling order cancellations.

TASK: Using ONLY the data inside <retrieved_data>, compose a clear, warm response about the order cancellation.

RULES:
  1. If cancellation was successful: confirm the cancellation, mention the order ID and refund timeline.
  2. If cancellation failed because the order already shipped:
     - Explain that the order cannot be cancelled once shipped.
     - Offer the alternative of initiating a return after delivery.
     - Do NOT apologise excessively — be direct and helpful.
  3. If cancellation failed due to order not found: apologise and ask them to verify the order ID.
  4. Use ONLY values from <retrieved_data> — never fabricate amounts or dates.
  5. Plain text, warm tone, 2-4 sentences. No markdown headers.
"""

_FALLBACK_CANCELLED = (
    "Your order {order_id} has been successfully cancelled. "
    "If payment was already captured, a full refund will be issued within 3-5 business days."
)
_FALLBACK_CANNOT_CANCEL = (
    "Unfortunately, order {order_id} cannot be cancelled because it has already been {status}. "
    "Once an order has shipped, it cannot be cancelled — but you can initiate a return "
    "once you receive it and we'll process a full refund."
)


def cancellations_node(state: AgentState) -> AgentState:
    """Attempt to cancel the customer's order and generate a confirmation or explanation."""
    order_id = state.get("order_id")
    customer_id = state.get("customer_id")
    customer_profile = state.get("customer_profile") or {}
    ticket_id = state.get("ticket_id")
    tool_calls_made: list[str] = list(state.get("tool_calls_made", []))

    # Extract the cancellation reason from the user's latest message
    messages = state.get("messages", [])
    user_text = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_text = str(msg.content)
            break
    reason = user_text[:200] if user_text else "Customer requested cancellation"

    cancellation_result: dict = {}

    if not order_id:
        cancellation_result = {
            "success": False,
            "error": "No order ID provided. Please specify which order you'd like to cancel.",
        }
    elif not customer_id:
        cancellation_result = {
            "success": False,
            "error": "Session error: customer identity could not be determined.",
        }
    else:
        try:
            result = cancel_order.invoke({
                "order_id": order_id,
                "customer_id": customer_id,
                "reason": reason,
            })
            tool_calls_made.append("cancel_order")
            cancellation_result = result

            # Send cancellation confirmation if successful
            if result.get("success") and ticket_id:
                try:
                    send_customer_notification.invoke({
                        "customer_id": customer_id,
                        "ticket_id": ticket_id,
                        "channel": "email",
                        "template": "cancellation",
                        "template_vars": {"order_id": order_id},
                    })
                    tool_calls_made.append("send_customer_notification")
                except Exception as exc:
                    logger.warning("Notification failed after cancel: %s", exc)

        except Exception as exc:
            logger.error("cancel_order tool call failed: %s", exc)
            cancellation_result = {"success": False, "error": str(exc)}

    # Build context for LLM response generation
    context_data: dict = {
        "cancellation": cancellation_result,
        "order_id": order_id or "N/A",
        "customer": {
            "name": customer_profile.get("name", "valued customer"),
            "is_vip": customer_profile.get("is_vip", False),
        },
    }

    llm = get_llm("cancellations")
    fallback: str
    if cancellation_result.get("success"):
        fallback = _FALLBACK_CANCELLED.format(order_id=order_id or "N/A")
    else:
        fallback = _FALLBACK_CANNOT_CANCEL.format(
            order_id=order_id or "N/A",
            status=cancellation_result.get("current_status", "processed"),
        )

    try:
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            SystemMessage(
                content="<retrieved_data>\n" + json.dumps(context_data, indent=2) + "\n</retrieved_data>"
            ),
            SystemMessage(content="Compose the cancellation response now."),
        ])
        message = response.content or fallback
    except Exception as exc:
        logger.error("Cancellations LLM call failed: %s — using fallback", exc)
        message = fallback

    return {
        **state,
        "cancellation_status": cancellation_result,
        "order_access_denied": cancellation_result.get("unauthorized", False),
        "final_response": message,
        "messages": messages + [AIMessage(content=message)],
        "tool_calls_made": tool_calls_made,
    }
