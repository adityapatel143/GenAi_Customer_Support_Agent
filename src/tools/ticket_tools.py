import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from langchain_core.tools import tool

from src.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


@tool
def create_ticket(
    customer_id: str,
    order_id: str | None,
    intent: str,
    priority: Literal["low", "normal", "high", "urgent"] = "normal",
    description: str | None = None,
) -> dict[str, Any]:
    """Create a new support ticket for a customer interaction.

    Creates a ticket record in the database with the given intent (wismo/return/refund/
    other/escalate) and priority level. Returns the new ticket ID to be stored in state.
    Always create a ticket at the start of a new support session.
    """
    try:
        client = get_supabase_client()
        ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        initial_conversation = []
        if description:
            initial_conversation = [{
                "role": "customer",
                "content": description[:250],
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }]
        payload = {
            "id": ticket_id,
            "customer_id": customer_id,
            "order_id": order_id,
            "intent": intent,
            "status": "open",
            "priority": priority,
            "conversation": initial_conversation,
        }
        client.table("tickets").insert(payload).execute()
        return {
            "success": True,
            "ticket_id": ticket_id,
            "status": "open",
            "priority": priority,
        }
    except Exception as exc:
        logger.error("create_ticket failed for customer %s: %s", customer_id, exc)
        return {"success": False, "error": str(exc)}


@tool
def update_ticket(
    ticket_id: str,
    status: Literal["open", "in_progress", "escalated", "resolved", "closed"],
    resolved_by: str | None = None,
) -> dict[str, Any]:
    """Update the status of an existing support ticket.

    Changes the ticket status and optionally sets the resolved_by field ('agent' or 'human').
    Use this at the end of each interaction to close or update the ticket.
    """
    try:
        client = get_supabase_client()
        update_data: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        if resolved_by:
            update_data["resolved_by"] = resolved_by
        result = (
            client.table("tickets")
            .update(update_data)
            .eq("id", ticket_id)
            .execute()
        )
        if not result.data:
            return {"success": False, "error": f"Ticket {ticket_id} not found"}
        return {"success": True, "ticket_id": ticket_id, "status": status}
    except Exception as exc:
        logger.error("update_ticket failed for %s: %s", ticket_id, exc)
        return {"success": False, "error": str(exc)}


@tool
def escalate_ticket(
    ticket_id: str,
    reason: str,
    priority: Literal["high", "urgent"] = "urgent",
) -> dict[str, Any]:
    """Escalate a support ticket to human agents with a specified priority.

    Updates the ticket status to 'escalated', sets priority to 'urgent' or 'high',
    and records the escalation reason. Use this when automatic resolution is not possible
    or when escalation conditions are met (fraud, VIP, high refund amount, customer anger).
    """
    try:
        client = get_supabase_client()
        update_data = {
            "status": "escalated",
            "priority": priority,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        result = (
            client.table("tickets")
            .update(update_data)
            .eq("id", ticket_id)
            .execute()
        )
        if not result.data:
            return {"success": False, "error": f"Ticket {ticket_id} not found"}

        logger.warning("Ticket %s escalated: %s (priority=%s)", ticket_id, reason, priority)
        return {
            "success": True,
            "ticket_id": ticket_id,
            "status": "escalated",
            "priority": priority,
            "reason": reason,
        }
    except Exception as exc:
        logger.error("escalate_ticket failed for %s: %s", ticket_id, exc)
        return {"success": False, "error": str(exc)}


@tool
def get_ticket(
    ticket_id: str,
    customer_id: str,
) -> dict[str, Any]:
    """Fetch the current status and details of a support ticket.

    Returns ticket status, priority, intent, and timestamps for the given ticket.
    Only returns the ticket if it belongs to the specified customer (ownership enforced).
    Use this before escalating to avoid double-escalation, or to include live ticket
    status in the customer-facing response.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("tickets")
            .select("id, customer_id, order_id, intent, status, priority, created_at, updated_at")
            .eq("id", ticket_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        if not result.data:
            return {"success": False, "error": f"Ticket {ticket_id} not found for this customer"}
        ticket = result.data[0]
        return {
            "success": True,
            "ticket_id": ticket["id"],
            "status": ticket["status"],
            "priority": ticket["priority"],
            "intent": ticket["intent"],
            "order_id": ticket.get("order_id"),
            "created_at": ticket.get("created_at"),
            "updated_at": ticket.get("updated_at"),
        }
    except Exception as exc:
        logger.error("get_ticket failed for %s: %s", ticket_id, exc)
        return {"success": False, "error": str(exc)}


@tool
def search_tickets(
    customer_id: str,
    status: str | None = None,
    intent: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search prior support tickets for a customer, optionally filtered by status or intent.

    Use this before escalating to check whether the same issue has been escalated
    recently (avoiding duplicate escalations), or to give the responder context
    about a customer's support history.

    status: "open" | "in_progress" | "escalated" | "resolved" | "closed" | None (all)
    intent: "wismo" | "return" | "refund" | "escalate" | "cancel" | None (all)
    limit: max results to return (default 5, max 20)

    Always pass the customer_id from the authenticated session.
    """
    try:
        client = get_supabase_client()
        limit = min(limit, 20)
        query = (
            client.table("tickets")
            .select("id, intent, status, priority, created_at, updated_at, resolved_by")
            .eq("customer_id", customer_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if status:
            query = query.eq("status", status)
        if intent:
            query = query.eq("intent", intent)

        result = query.execute()
        tickets = result.data or []
        return {
            "success": True,
            "customer_id": customer_id,
            "tickets": tickets,
            "count": len(tickets),
        }
    except Exception as exc:
        logger.error("search_tickets failed for customer %s: %s", customer_id, exc)
        return {"success": False, "error": str(exc), "customer_id": customer_id}

