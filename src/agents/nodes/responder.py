"""Responder node: generates the final customer-facing response with guardrails."""
from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.state import AgentState
from src.config import get_llm, get_settings
from src.tools.notification_tools import send_customer_notification
from src.tools.ticket_tools import create_ticket, get_ticket, search_tickets, update_ticket

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """ROLE: You are a professional, empathetic e-commerce customer support agent composing the final reply to a customer.

TASK: Using ONLY the data inside <retrieved_data>, compose a clear, warm, solution-oriented response that directly addresses the customer's intent.

DATA GROUNDING RULES:
  1. Every factual value (order status, item name, tracking number, carrier, amount, date, RMA number)
     MUST come from a field present in <retrieved_data>. Never guess, estimate, or invent values.
  2. If a field is absent from <retrieved_data>, omit it entirely — do not substitute a placeholder.
  3. Never expose internal IDs (customer_id, database record IDs) that are not order-facing.
  4. If intent is 'wismo' and <retrieved_data> contains no order or order_history, tell the
     customer you could not retrieve that order and ask them to verify the order ID.

RESPONSE TEMPLATES BY INTENT (map field names directly from <retrieved_data>):

  intent=wismo, single order  →  use retrieved_data.order:
    Order ID : [order.id]
    Status   : [order.status]
    Items    : [each item in order.items — name × qty]
    Total    : $[order.total_amount]
    Carrier  : [order.carrier]   Tracking : [order.tracking_number]
    Est. Delivery : [order.estimated_delivery]
    • shipped   → always include carrier + tracking number
    • delivered → confirm delivery, offer returns/refunds help
    • processing/pending → state no tracking yet, give estimated delivery
    • cancelled → state cancellation, offer next steps

  intent=wismo, order history  →  use retrieved_data.order_history[]:
    For each order: [id] | [status] | [items summary] | $[total_amount] | ordered [ordered_at]

  intent=return  →  use retrieved_data.return_eligibility and retrieved_data.rma:
    • eligible=true + rma present  : confirm RMA [rma.rma_number], share [rma.label_url], state [return_eligibility.days_remaining] days remaining
    • eligible=true + no rma       : confirm eligibility, explain next steps
    • eligible=false               : quote the exact [return_eligibility.reason]; do not invent alternatives
    • existing_return present      : reference [return_eligibility.existing_return.id] and its status; do not create a duplicate

  intent=refund  →  use retrieved_data.refund:
    • refund_status=refunded       : confirm $[refund.refund_amount] has been processed
    • refund_status=processing     : warehouse received item; $[refund.refund_amount] refund in 3-5 business days
    • refund_status=awaiting_return: RMA [refund.rma_number] created; waiting for item to arrive at warehouse
    • refund_found=false           : no return/refund on record; suggest initiating a return first

  intent=other, ticket history query  →  use retrieved_data.ticket_history[]:
    List every ticket:
      Ticket ID | Status | Priority | Intent | Created
    If the list is empty, tell the customer they have no support tickets on file.
    Never invent ticket IDs or statuses — use only values from retrieved_data.ticket_history.

  intent=other, ticket status query  →  use retrieved_data.requested_ticket:
    • success=true  : report ticket ID, current status, priority, and creation date
    • success=false : inform the customer that no ticket with that ID was found on their account
    Do NOT invent any ticket data. Use only values from retrieved_data.requested_ticket.

FORMAT: Plain text with line breaks between key fields. Warm and professional tone. No markdown headers.
"""


def responder_node(state: AgentState) -> AgentState:
    """Generate the final response using all collected state data, then validate with guardrails."""
    settings = get_settings()
    llm = get_llm("responder")

    intent = state.get("intent", "other")
    order_data = state.get("order_data") or {}
    orders_list: list = state.get("orders_list") or []
    order_access_denied: bool = state.get("order_access_denied", False)
    return_eligibility = state.get("return_eligibility") or {}
    rma_data = state.get("rma_data") or {}
    refund_status: dict = state.get("refund_status") or {}
    customer_profile = state.get("customer_profile") or {}
    ticket_id = state.get("ticket_id")
    tool_calls_made: list[str] = list(state.get("tool_calls_made", []))

    # Build structured context data block — each key maps to a template field in the system prompt
    context_data: dict = {}
    if customer_profile.get("name"):
        context_data["customer"] = {
            "name": customer_profile.get("name"),
            "is_vip": customer_profile.get("is_vip", False),
        }
    if orders_list:
        context_data["order_history"] = orders_list
    if order_data:
        context_data["order"] = order_data
    if return_eligibility:
        context_data["return_eligibility"] = return_eligibility
    if rma_data:
        context_data["rma"] = rma_data
    if refund_status:
        context_data["refund"] = refund_status

    # If the customer asked for their full ticket history, fetch it via search_tickets.
    if state.get("ticket_history_requested") and state.get("customer_id"):
        try:
            ticket_history_result = search_tickets.invoke({
                "customer_id": state["customer_id"],
                "limit": 10,
            })
            context_data["ticket_history"] = ticket_history_result.get("tickets", [])
            tool_calls_made.append("search_tickets")
            logger.info(
                "Responder fetched ticket history for customer %s: %d tickets",
                state["customer_id"], len(context_data["ticket_history"]),
            )
        except Exception as exc:
            logger.warning("search_tickets failed in responder: %s", exc)

    # Fetch live ticket status so the LLM can accurately report it to the customer
    if ticket_id and state.get("customer_id"):
        try:
            ticket_info = get_ticket.invoke({
                "ticket_id": ticket_id,
                "customer_id": state["customer_id"],
            })
            if ticket_info.get("success"):
                context_data["ticket"] = {
                    "id": ticket_info["ticket_id"],
                    "status": ticket_info["status"],
                    "priority": ticket_info["priority"],
                }
                tool_calls_made.append("get_ticket")
        except Exception as exc:
            logger.warning("get_ticket failed in responder: %s", exc)

    # If the customer asked about a specific ticket by ID (e.g. "status of TKT-001"),
    # look it up and add it as requested_ticket so the LLM can respond accurately.
    # This is separate from the session's current ticket_id.
    _TKT_RE = re.compile(r"\b(TKT-[A-Z0-9]+)\b", re.IGNORECASE)
    user_text = ""
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            user_text = str(msg.content)
            break
    tkt_match = _TKT_RE.search(user_text)
    if tkt_match and state.get("customer_id"):
        mentioned_ticket_id = tkt_match.group(1).upper()
        # Only look up if it's different from the already-fetched session ticket
        if mentioned_ticket_id != ticket_id:
            try:
                req_ticket = get_ticket.invoke({
                    "ticket_id": mentioned_ticket_id,
                    "customer_id": state["customer_id"],
                })
                context_data["requested_ticket"] = req_ticket
                tool_calls_made.append("get_ticket")
                logger.info(
                    "Responder fetched requested ticket %s for customer %s",
                    mentioned_ticket_id, state["customer_id"],
                )
            except Exception as exc:
                logger.warning("get_ticket for requested ticket %s failed: %s", mentioned_ticket_id, exc)

    messages: list = [SystemMessage(content=_SYSTEM_PROMPT)]
    if context_data:
        messages.append(SystemMessage(
            content="<retrieved_data>\n" + json.dumps(context_data, indent=2) + "\n</retrieved_data>"
        ))

    for msg in state.get("messages", []):
        messages.append(msg)

    if order_access_denied:
        requested_order = state.get("order_id", "the requested order")
        messages.append(SystemMessage(
            content=(
                f"IMPORTANT: The customer asked about order {requested_order}, but that order "
                "does NOT belong to their account. You must NOT show any order details, "
                "must NOT make up or guess any order information. "
                "Politely inform the customer that no order with that ID was found on their account, "
                "and suggest they double-check the order ID."
            )
        ))

    messages.append(SystemMessage(
        content=json.dumps({
            "intent": intent,
            "ticket_id": ticket_id or "N/A",
            "instruction": "Apply the response template for this intent. Use only field values from <retrieved_data>. Compose the final customer response now.",
        })
    ))

    safe_fallback = (
        "Thank you for contacting us. We're looking into your request and will "
        "follow up shortly. Your ticket reference is: " + (ticket_id or "N/A") + "."
    )

    try:
        response = llm.invoke(messages)
        raw_response = response.content or safe_fallback
    except Exception as exc:
        logger.error("Responder LLM call failed: %s", exc)
        raw_response = safe_fallback

    # output_guardrail_node runs after this node and handles:
    # - PII redaction, toxic language, factual consistency
    # - access-denied containment
    # All of these are visible as a separate span in LangSmith.
    final_response = raw_response

    # Mark ticket as in_progress — stays open during the conversation.
    # Resolved only when customer clicks "Close Ticket" or starts a new session.
    if ticket_id:
        try:
            update_ticket.invoke({
                "ticket_id": ticket_id,
                "status": "in_progress",
                "resolved_by": None,
            })
            tool_calls_made.append("update_ticket")
        except Exception as exc:
            logger.warning("Failed to update ticket %s: %s", ticket_id, exc)

    # Send a confirmation notification after key fulfilment events.
    notification_sent = state.get("notification_sent", False)
    customer_id = state.get("customer_id")
    if ticket_id and customer_id and not notification_sent:
        rma_data = state.get("rma_data") or {}
        refund_st = state.get("refund_status") or {}
        notif_template: str | None = None
        notif_vars: dict = {}

        if rma_data.get("rma_number"):
            notif_template = "rma_created"
            notif_vars = {
                "rma_number": rma_data["rma_number"],
                "label_url": rma_data.get("label_url", "N/A"),
            }
        elif refund_st.get("refund_status") == "refunded" and refund_st.get("refund_amount"):
            notif_template = "refund_processed"
            notif_vars = {
                "amount": refund_st["refund_amount"],
                "order_id": state.get("order_id", "N/A"),
            }

        if notif_template:
            try:
                notif = send_customer_notification.invoke({
                    "customer_id": customer_id,
                    "ticket_id": ticket_id,
                    "channel": "email",
                    "template": notif_template,
                    "template_vars": notif_vars,
                })
                notification_sent = notif.get("success", False)
                if notification_sent:
                    tool_calls_made.append("send_customer_notification")
            except Exception as exc:
                logger.warning("send_customer_notification failed in responder: %s", exc)

    return {
        **state,
        "final_response": final_response,
        "notification_sent": notification_sent,
        "messages": state.get("messages", []) + [AIMessage(content=final_response)],
        "tool_calls_made": tool_calls_made,
    }
