import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool

from src.config import get_settings
from src.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


@tool
def check_return_eligibility(order_id: str, customer_id: str) -> dict[str, Any]:
    """Check whether an order is eligible for return.

    An order is eligible if: its status is 'delivered' AND the number of days since
    delivery is within the configured return window (default 30 days). Returns eligibility
    status, reason, days remaining in the return window, and order details.
    Always pass the customer_id from the session context so ownership is verified.
    Returns an access-denied error if the order does not belong to this customer.
    Use this before initiating any return or RMA process.
    """
    try:
        settings = get_settings()
        client = get_supabase_client()

        order_result = (
            client.table("orders")
            .select("id, status, shipped_at, estimated_delivery, total_amount, customer_id")
            .eq("id", order_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        if not order_result.data:
            logger.warning(
                "Ownership check failed: order %s not found for customer %s",
                order_id, customer_id,
            )
            return {
                "eligible": False,
                "reason": "Order not found or does not belong to your account.",
                "order_id": order_id,
                "unauthorized": True,
            }

        order = order_result.data[0]
        if order["status"] != "delivered":
            return {
                "eligible": False,
                "reason": f"Order status is '{order['status']}', must be 'delivered' to return.",
                "order_id": order_id,
                "order_status": order["status"],
            }

        # Use estimated_delivery as delivery date; fall back to shipped_at + 5 days heuristic
        delivery_str = order.get("estimated_delivery") or order.get("shipped_at")
        if not delivery_str:
            return {"eligible": False, "reason": "No delivery date on record.", "order_id": order_id}

        delivery_dt = datetime.fromisoformat(delivery_str.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        days_since = (now - delivery_dt).days
        window = settings.return_window_days
        days_remaining = window - days_since

        if days_since > window:
            return {
                "eligible": False,
                "reason": f"Return window of {window} days has expired ({days_since} days since delivery).",
                "order_id": order_id,
                "days_since_delivery": days_since,
                "return_window_days": window,
            }

        # Check for existing return requests
        existing = (
            client.table("return_requests")
            .select("id, status")
            .eq("order_id", order_id)
            .execute()
        )
        if existing.data:
            return {
                "eligible": False,
                "reason": "A return request already exists for this order.",
                "order_id": order_id,
                "existing_return": existing.data[0],
            }

        return {
            "eligible": True,
            "reason": "Order is within return window and eligible for return.",
            "order_id": order_id,
            "customer_id": order["customer_id"],
            "total_amount": order["total_amount"],
            "days_since_delivery": days_since,
            "days_remaining": days_remaining,
            "return_window_days": window,
        }
    except Exception as exc:
        logger.error("check_return_eligibility failed for %s: %s", order_id, exc)
        return {"eligible": False, "error": str(exc), "order_id": order_id}


@tool
def create_rma(order_id: str, reason: str, customer_id: str) -> dict[str, Any]:
    """Create a Return Merchandise Authorization (RMA) for an eligible order.

    This inserts a return_request record and an rma_record, generates a unique RMA number,
    and provides a shipping label URL. Only call this after confirming eligibility with
    check_return_eligibility. Returns the RMA number, label URL, and return request ID.
    """
    try:
        client = get_supabase_client()
        settings = get_settings()

        ret_id = f"RET-{uuid.uuid4().hex[:8].upper()}"
        rma_id = f"RMA-{uuid.uuid4().hex[:8].upper()}"
        rma_number = f"RMA-{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        label_url = f"https://labels.example.com/{rma_id.lower()}.pdf"

        ret_payload = {
            "id": ret_id,
            "order_id": order_id,
            "customer_id": customer_id,
            "reason": reason,
            "status": "approved",
            "return_window_days": settings.return_window_days,
        }
        client.table("return_requests").insert(ret_payload).execute()

        rma_payload = {
            "id": rma_id,
            "return_request_id": ret_id,
            "rma_number": rma_number,
            "label_url": label_url,
        }
        client.table("rma_records").insert(rma_payload).execute()

        return {
            "success": True,
            "return_request_id": ret_id,
            "rma_id": rma_id,
            "rma_number": rma_number,
            "label_url": label_url,
            "order_id": order_id,
            "customer_id": customer_id,
            "message": f"RMA created successfully. Ship your item using label: {label_url}",
        }
    except Exception as exc:
        logger.error("create_rma failed for %s: %s", order_id, exc)
        return {"success": False, "error": str(exc), "order_id": order_id}


@tool
def get_return_status(return_id: str, customer_id: str) -> dict[str, Any]:
    """Get the current status of an existing return request by its return ID (e.g. RET-003).

    Use this when the customer asks about the status of a specific return request they
    already have. Verifies ownership via customer_id before returning any data.
    Returns the return request details, its current status, and any associated RMA info.
    Always pass the customer_id from the session context so ownership is verified.
    """
    try:
        client = get_supabase_client()

        ret_result = (
            client.table("return_requests")
            .select("id, order_id, customer_id, reason, status, requested_at, approved_at, return_window_days")
            .eq("id", return_id)
            .execute()
        )

        if not ret_result.data:
            return {
                "found": False,
                "return_id": return_id,
                "message": f"No return request found with ID {return_id}.",
            }

        ret = ret_result.data[0]

        # Ownership check
        if ret["customer_id"] != customer_id:
            logger.warning(
                "Ownership check failed: return %s does not belong to customer %s",
                return_id, customer_id,
            )
            return {
                "found": False,
                "return_id": return_id,
                "unauthorized": True,
                "message": "Return request not found or does not belong to your account.",
            }

        # Look up associated RMA record
        rma_result = (
            client.table("rma_records")
            .select("rma_number, label_url, warehouse_received_at, refund_amount, created_at")
            .eq("return_request_id", return_id)
            .execute()
        )

        response: dict[str, Any] = {
            "found": True,
            "return_id": return_id,
            "order_id": ret["order_id"],
            "reason": ret["reason"],
            "status": ret["status"],
            "requested_at": ret["requested_at"],
            "approved_at": ret["approved_at"],
        }

        if rma_result.data:
            rma = rma_result.data[0]
            response["rma_number"] = rma["rma_number"]
            response["label_url"] = rma["label_url"]
            response["warehouse_received_at"] = rma["warehouse_received_at"]
            response["refund_amount"] = rma["refund_amount"]

        return response

    except Exception as exc:
        logger.error("get_return_status failed for %s: %s", return_id, exc)
        return {"found": False, "error": str(exc), "return_id": return_id}
