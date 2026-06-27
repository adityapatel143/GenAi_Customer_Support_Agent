import logging
from typing import Any

from langchain_core.tools import tool

from src.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


@tool
def check_refund_status(order_id: str, customer_id: str) -> dict[str, Any]:
    """Check the current refund status for an order.

    Looks up return requests and associated RMA records to determine whether a refund
    has been initiated, the refund amount, and RMA details. Use this when a customer
    asks about the status of their refund.
    Always pass the customer_id from the session context so ownership is verified.
    Returns an access-denied error if the order does not belong to this customer.
    """
    try:
        client = get_supabase_client()

        ret_result = (
            client.table("return_requests")
            .select("id, status, reason, requested_at, approved_at")
            .eq("order_id", order_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        if not ret_result.data:
            # Check if the order exists at all but belongs to someone else
            order_check = (
                client.table("orders")
                .select("id")
                .eq("id", order_id)
                .eq("customer_id", customer_id)
                .execute()
            )
            if not order_check.data:
                logger.warning(
                    "Ownership check failed: order %s not found for customer %s",
                    order_id, customer_id,
                )
                return {
                    "refund_found": False,
                    "order_id": order_id,
                    "unauthorized": True,
                    "message": "Order not found or does not belong to your account.",
                }
            return {
                "refund_found": False,
                "order_id": order_id,
                "message": "No return or refund request found for this order.",
            }

        ret = ret_result.data[0]
        rma_result = (
            client.table("rma_records")
            .select("*")
            .eq("return_request_id", ret["id"])
            .execute()
        )

        if not rma_result.data:
            return {
                "refund_found": True,
                "order_id": order_id,
                "return_status": ret["status"],
                "refund_status": "pending_rma",
                "message": "Return request exists but RMA has not been created yet.",
            }

        rma = rma_result.data[0]
        refund_amount = rma.get("refund_amount")
        warehouse_received = rma.get("warehouse_received_at")

        if refund_amount is not None and warehouse_received:
            refund_status = "refunded"
            message = f"Refund of ${refund_amount:.2f} has been processed."
        elif warehouse_received:
            refund_status = "processing"
            message = "Item received at warehouse. Refund is being processed (3-5 business days)."
        else:
            refund_status = "awaiting_return"
            message = "RMA created. We are waiting to receive your returned item."

        return {
            "refund_found": True,
            "order_id": order_id,
            "return_request_id": ret["id"],
            "rma_id": rma["id"],
            "rma_number": rma["rma_number"],
            "return_status": ret["status"],
            "refund_status": refund_status,
            "refund_amount": refund_amount,
            "warehouse_received_at": warehouse_received,
            "message": message,
        }
    except Exception as exc:
        logger.error("check_refund_status failed for %s: %s", order_id, exc)
        return {"refund_found": False, "error": str(exc), "order_id": order_id}


@tool
def initiate_refund(rma_id: str, amount: float) -> dict[str, Any]:
    """Initiate a refund for a completed RMA record.

    Updates the rma_records table with the refund amount and marks the refund as initiated.
    Only call this when the RMA item has been received at the warehouse. This simulates
    the refund initiation process (in production would call payment gateway).
    Returns confirmation with refund amount and expected timeline.
    """
    try:
        client = get_supabase_client()
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc).isoformat()

        result = (
            client.table("rma_records")
            .update({"refund_amount": amount, "warehouse_received_at": now})
            .eq("id", rma_id)
            .execute()
        )
        if not result.data:
            return {"success": False, "error": f"RMA {rma_id} not found", "rma_id": rma_id}

        return {
            "success": True,
            "rma_id": rma_id,
            "refund_amount": amount,
            "estimated_days": "3-5 business days",
            "message": f"Refund of ${amount:.2f} has been initiated. You will receive it in 3-5 business days.",
        }
    except Exception as exc:
        logger.error("initiate_refund failed for %s: %s", rma_id, exc)
        return {"success": False, "error": str(exc), "rma_id": rma_id}
