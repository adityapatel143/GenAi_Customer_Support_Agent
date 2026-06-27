"""Store credit tools: apply and fetch goodwill / compensation credits for customers."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from langchain_core.tools import tool

from src.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


@tool
def apply_store_credit(
    customer_id: str,
    amount: float,
    reason: str,
    issued_by: Literal["agent", "human"] = "agent",
) -> dict[str, Any]:
    """Apply a store credit (goodwill or compensation) to a customer's account.

    Creates a credit record in the store_credits table. Use this when:
    - The escalation node wants to offer a goodwill gesture (e.g. delayed delivery)
    - A human agent approves a compensation credit during ticket review
    - An order issue warrants a partial credit without a full refund

    The credit is valid for 12 months and can be applied against future orders.
    amount must be > 0 and should not exceed the original order total.
    Always pass the customer_id from the authenticated session.
    """
    if amount <= 0:
        return {"success": False, "error": "Credit amount must be greater than zero."}

    try:
        client = get_supabase_client()
        credit_id = f"CRD-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(tz=timezone.utc)

        payload: dict[str, Any] = {
            "id": credit_id,
            "customer_id": customer_id,
            "amount": round(amount, 2),
            "reason": reason,
            "issued_by": issued_by,
            "status": "active",
            "issued_at": now.isoformat(),
            "expires_at": now.replace(year=now.year + 1).isoformat(),
        }
        client.table("store_credits").insert(payload).execute()

        logger.info(
            "Store credit %s applied: $%.2f to customer %s by %s — %s",
            credit_id, amount, customer_id, issued_by, reason,
        )
        return {
            "success": True,
            "credit_id": credit_id,
            "customer_id": customer_id,
            "amount": round(amount, 2),
            "status": "active",
            "expires_at": payload["expires_at"][:10],
            "message": (
                f"A store credit of ${amount:.2f} has been added to your account. "
                f"It is valid for 12 months and will be applied automatically at checkout."
            ),
        }
    except Exception as exc:
        logger.error("apply_store_credit failed for customer %s: %s", customer_id, exc)
        return {"success": False, "error": str(exc)}


@tool
def get_store_credits(customer_id: str) -> dict[str, Any]:
    """Fetch all active store credits for a customer.

    Returns the list of active credits with amount, reason, and expiry date.
    Use this in escalation or responder context to inform the customer of any
    credits already on their account before applying a new one.
    Always pass the customer_id from the authenticated session.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("store_credits")
            .select("id, amount, reason, issued_by, status, issued_at, expires_at")
            .eq("customer_id", customer_id)
            .order("issued_at", desc=True)
            .execute()
        )
        credits = result.data or []
        active = [c for c in credits if c.get("status") == "active"]
        total_active = sum(c["amount"] for c in active)

        return {
            "success": True,
            "customer_id": customer_id,
            "credits": credits,
            "active_count": len(active),
            "total_active_amount": round(total_active, 2),
        }
    except Exception as exc:
        logger.error("get_store_credits failed for customer %s: %s", customer_id, exc)
        return {"success": False, "error": str(exc), "customer_id": customer_id}
