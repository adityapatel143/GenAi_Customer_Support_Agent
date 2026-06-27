"""Notification tools: simulate sending email/SMS confirmations to customers."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from langchain_core.tools import tool

from src.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# Template bodies used when no custom body is provided
_TEMPLATES: dict[str, str] = {
    "rma_created": (
        "Your return has been authorised (RMA: {rma_number}). "
        "Please use the prepaid label at {label_url} to ship the item back. "
        "Refunds are processed within 5-7 business days of warehouse receipt."
    ),
    "refund_processed": (
        "Great news — your refund of ${amount:.2f} for order {order_id} has been processed. "
        "Please allow 3-5 business days for it to appear in your account."
    ),
    "escalation": (
        "Your support case (ticket {ticket_id}) has been escalated to our specialist team. "
        "You will receive a personal response within 1-2 hours."
    ),
    "cancellation": (
        "Your order {order_id} has been successfully cancelled. "
        "If payment was captured, a full refund will be issued within 3-5 business days."
    ),
    "store_credit": (
        "A store credit of ${amount:.2f} has been added to your account as a goodwill gesture. "
        "It will be applied automatically at checkout and is valid for 12 months."
    ),
    "generic": (
        "Thank you for contacting support. Your ticket reference is {ticket_id}. "
        "Our team will follow up with you shortly."
    ),
}


@tool
def send_customer_notification(
    customer_id: str,
    ticket_id: str | None,
    channel: Literal["email", "sms"] = "email",
    template: Literal["rma_created", "refund_processed", "escalation", "cancellation", "store_credit", "generic"] = "generic",
    template_vars: dict | None = None,
) -> dict[str, Any]:
    """Send an email or SMS notification to a customer using a predefined template.

    Simulates dispatching a transactional message (in production this would call
    SendGrid, Twilio, etc.) and logs the notification record to the database.

    Use this after key events:
    - rma_created       : after create_rma succeeds
    - refund_processed  : after initiate_refund succeeds
    - escalation        : after escalate_ticket succeeds
    - cancellation      : after cancel_order succeeds
    - store_credit      : after apply_store_credit succeeds
    - generic           : general status update

    template_vars is a dict of substitution values for the template body
    (e.g. {"rma_number": "RMA-1234", "label_url": "https://..."}).
    Always pass the customer_id from the authenticated session.
    """
    try:
        client = get_supabase_client()

        # Resolve customer email (needed for email channel)
        cust_result = (
            client.table("customers")
            .select("email, name")
            .eq("id", customer_id)
            .execute()
        )
        customer = cust_result.data[0] if cust_result.data else {}
        recipient = customer.get("email") if channel == "email" else f"SMS:{customer_id}"

        # Build body from template
        vars_with_defaults = {"ticket_id": ticket_id or "N/A", **(template_vars or {})}
        try:
            body = _TEMPLATES[template].format(**vars_with_defaults)
        except KeyError:
            body = _TEMPLATES["generic"].format(**vars_with_defaults)

        notification_id = f"NTF-{uuid.uuid4().hex[:8].upper()}"
        payload: dict[str, Any] = {
            "id": notification_id,
            "customer_id": customer_id,
            "ticket_id": ticket_id,
            "channel": channel,
            "template": template,
            "recipient": recipient,
            "body": body,
            "status": "sent",   # simulated — always succeeds in demo
            "sent_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        client.table("notifications").insert(payload).execute()

        logger.info(
            "Notification %s sent to %s via %s (template=%s, ticket=%s)",
            notification_id, recipient, channel, template, ticket_id,
        )
        return {
            "success": True,
            "notification_id": notification_id,
            "channel": channel,
            "template": template,
            "recipient": recipient,
            "message": f"Confirmation {channel} sent to {recipient}.",
        }
    except Exception as exc:
        logger.error(
            "send_customer_notification failed for customer %s: %s", customer_id, exc
        )
        return {"success": False, "error": str(exc), "customer_id": customer_id}
