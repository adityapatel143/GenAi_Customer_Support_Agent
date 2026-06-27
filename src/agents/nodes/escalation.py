"""Escalation node: handles human escalation with ticket updates."""
from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, SystemMessage

from src.agents.state import AgentState
from src.config import get_llm, get_settings
from src.tools.credit_tools import apply_store_credit
from src.tools.notification_tools import send_customer_notification
from src.tools.ticket_tools import escalate_ticket, get_ticket, search_tickets

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """ROLE: You are an empathetic senior e-commerce customer support specialist.

TASK: Compose a warm, professional escalation handoff message to inform the customer that
their case is being transferred to a human specialist.

RULES:
  1. Address the customer by name using customer.name from <context>.
  2. Acknowledge the specific situation using the escalation_reasons from <context>.
     - If the customer explicitly asked for a human — acknowledge their request directly.
     - If it is a high-value order or VIP case — emphasise priority treatment.
     - If there were technical difficulties — apologise and reassure.
  3. Always include: ticket reference (ticket_id), expected response time (1-2 hours).
  4. Keep the tone warm, sincere, and solution-oriented. 3-5 sentences maximum.
  5. Do NOT mention fraud scores, internal thresholds, or system errors.
  6. Do NOT reveal the internal escalation_reasons verbatim.
"""

_FALLBACK_TEMPLATE = (
    "I understand your frustration, {name}, and I sincerely apologize for the inconvenience. "
    "I'm connecting you with one of our specialist agents right now who can provide you with "
    "the highest level of support. You will receive a response within 1-2 hours. "
    "Your ticket has been escalated with priority status. Reference: {ticket_id}."
)


def escalation_node(state: AgentState) -> AgentState:
    """Set requires_human=True, escalate the ticket, and generate an LLM handoff message."""
    ticket_id = state.get("ticket_id")
    customer_profile = state.get("customer_profile") or {}
    order_data = state.get("order_data") or {}
    intent = state.get("intent", "escalate")
    tool_calls_made: list[str] = list(state.get("tool_calls_made", []))
    error_count: int = state.get("tool_error_count", 0)
    settings = get_settings()

    # Determine escalation reasons (internal, not exposed to customer)
    reasons: list[str] = []
    if state.get("escalation_reason"):
        reasons.append(state["escalation_reason"])
    if customer_profile.get("fraud_score", 0.0) > settings.fraud_score_threshold:
        reasons.append("High fraud score detected")
    if customer_profile.get("is_vip"):
        reasons.append("VIP customer requires priority handling")
    refund_amount = order_data.get("total_amount", 0.0)
    if refund_amount > settings.escalation_refund_threshold:
        reasons.append(f"High-value order ${refund_amount:.2f} exceeds threshold")
    if error_count >= settings.max_auto_retries:
        reasons.append(f"Technical difficulties after {error_count} retries")
    if intent == "escalate":
        reasons.append("Customer explicitly requested a human agent")

    escalation_reason = "; ".join(reasons) if reasons else "Customer requested escalation"

    # Escalate the ticket in the database — skip if already escalated
    if ticket_id:
        try:
            current = get_ticket.invoke({"ticket_id": ticket_id, "customer_id": state["customer_id"]})
            already_escalated = current.get("success") and current.get("status") == "escalated"
            if not already_escalated:
                escalate_ticket.invoke({
                    "ticket_id": ticket_id,
                    "reason": escalation_reason,
                    "priority": "urgent",
                })
                tool_calls_made.append("escalate_ticket")
            else:
                logger.info("Ticket %s already escalated — skipping duplicate escalation", ticket_id)
            tool_calls_made.append("get_ticket")
        except Exception as exc:
            logger.error("Failed to escalate ticket %s: %s", ticket_id, exc)

    # Check prior escalations for this customer (avoids redundant escalation messages)
    prior_escalations: list[dict] = []
    if state.get("customer_id"):
        try:
            search_result = search_tickets.invoke({
                "customer_id": state["customer_id"],
                "status": "escalated",
                "limit": 3,
            })
            prior_escalations = search_result.get("tickets", []) if search_result.get("success") else []
            tool_calls_made.append("search_tickets")
        except Exception as exc:
            logger.warning("search_tickets failed in escalation: %s", exc)

    # Apply a goodwill store credit for VIP customers or high-value order delays
    store_credit_result: dict = {}
    is_vip = customer_profile.get("is_vip", False)
    high_value = refund_amount > settings.escalation_refund_threshold
    if (is_vip or high_value) and state.get("customer_id"):
        credit_amount = 15.0 if is_vip else 10.0
        try:
            store_credit_result = apply_store_credit.invoke({
                "customer_id": state["customer_id"],
                "amount": credit_amount,
                "reason": f"Goodwill credit — escalation ({escalation_reason[:80]})",
                "issued_by": "agent",
            })
            if store_credit_result.get("success"):
                tool_calls_made.append("apply_store_credit")
                logger.info(
                    "Store credit $%.2f applied for customer %s during escalation",
                    credit_amount, state["customer_id"],
                )
        except Exception as exc:
            logger.warning("apply_store_credit failed during escalation: %s", exc)

    # Send escalation notification email
    notification_sent = False
    if ticket_id and state.get("customer_id"):
        try:
            notif = send_customer_notification.invoke({
                "customer_id": state["customer_id"],
                "ticket_id": ticket_id,
                "channel": "email",
                "template": "escalation",
                "template_vars": {"ticket_id": ticket_id},
            })
            notification_sent = notif.get("success", False)
            if notification_sent:
                tool_calls_made.append("send_customer_notification")
        except Exception as exc:
            logger.warning("Escalation notification failed: %s", exc)

    customer_name = customer_profile.get("name", "valued customer")

    # Build structured context for the LLM
    ctx = {
        "customer": {
            "name": customer_name,
            "is_vip": customer_profile.get("is_vip", False),
        },
        "ticket_id": ticket_id or "N/A",
        "escalation_reasons": reasons,
        "order_id": order_data.get("id"),
        "store_credit_applied": store_credit_result.get("amount") if store_credit_result.get("success") else None,
        "prior_escalation_count": len(prior_escalations),
    }

    # LLM-generated handoff message
    fallback = _FALLBACK_TEMPLATE.format(name=customer_name, ticket_id=ticket_id or "N/A")
    try:
        llm = get_llm("escalation")
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            SystemMessage(content="<context>\n" + json.dumps(ctx, indent=2) + "\n</context>"),
            SystemMessage(content="Compose the escalation handoff message now."),
        ])
        message = response.content or fallback
    except Exception as exc:
        logger.error("Escalation LLM call failed: %s — using fallback", exc)
        message = fallback

    logger.warning(
        "Escalation triggered for customer %s, ticket %s: %s",
        state.get("customer_id"),
        ticket_id,
        escalation_reason,
    )

    return {
        **state,
        "requires_human": True,
        "escalation_reason": escalation_reason,
        "store_credit_applied": store_credit_result if store_credit_result.get("success") else state.get("store_credit_applied"),
        "notification_sent": notification_sent,
        "final_response": message,
        "messages": state.get("messages", []) + [AIMessage(content=message)],
        "tool_calls_made": tool_calls_made,
    }
