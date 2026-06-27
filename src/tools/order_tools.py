import logging
from typing import Any

from langchain_core.tools import tool

from src.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


@tool
def get_order_status(order_id: str, customer_id: str) -> dict[str, Any]:
    """Get the current status of an order by order ID.

    Returns the order ID, status (pending/processing/shipped/delivered/cancelled),
    carrier, tracking number, estimated delivery date, and shipped date.
    Always pass the customer_id from the session context so ownership is verified.
    Returns an access-denied error if the order does not belong to this customer.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("orders")
            .select("id, status, carrier, tracking_number, estimated_delivery, shipped_at, ordered_at, customer_id")
            .eq("id", order_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        if not result.data:
            logger.warning(
                "Ownership check failed: order %s not found for customer %s",
                order_id, customer_id,
            )
            return {
                "error": "Order not found or does not belong to your account.",
                "order_id": order_id,
                "unauthorized": True,
            }
        return {"success": True, **result.data[0]}
    except Exception as exc:
        logger.error("get_order_status failed for %s: %s", order_id, exc)
        return {"error": str(exc), "order_id": order_id}


@tool
def get_order_details(order_id: str, customer_id: str) -> dict[str, Any]:
    """Get full details of an order including items, amounts, carrier, and tracking.

    Returns the complete order record with items list (sku, name, qty, price),
    total_amount, carrier, tracking_number, all dates, and customer_id.
    Always pass the customer_id from the session context so ownership is verified.
    Returns an access-denied error if the order does not belong to this customer.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("orders")
            .select("*")
            .eq("id", order_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        if not result.data:
            logger.warning(
                "Ownership check failed: order %s not found for customer %s",
                order_id, customer_id,
            )
            return {
                "error": "Order not found or does not belong to your account.",
                "order_id": order_id,
                "unauthorized": True,
            }
        return {"success": True, **result.data[0]}
    except Exception as exc:
        logger.error("get_order_details failed for %s: %s", order_id, exc)
        return {"error": str(exc), "order_id": order_id}


@tool
def get_customer_orders(customer_id: str) -> dict[str, Any]:
    """Get all orders for a customer, sorted newest first.

    Use this when the customer asks about 'my orders', 'past orders', 'order history',
    or any question about their orders without specifying a particular order ID.
    Returns a list of orders with id, status, total_amount, items, ordered_at,
    carrier, tracking_number, and estimated_delivery for each order.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("orders")
            .select("id, status, total_amount, items, ordered_at, shipped_at, estimated_delivery, carrier, tracking_number")
            .eq("customer_id", customer_id)
            .order("ordered_at", desc=True)
            .execute()
        )
        orders = result.data or []
        return {"success": True, "customer_id": customer_id, "orders": orders, "count": len(orders)}
    except Exception as exc:
        logger.error("get_customer_orders failed for %s: %s", customer_id, exc)
        return {"error": str(exc), "customer_id": customer_id}


@tool
def cancel_order(order_id: str, customer_id: str, reason: str) -> dict[str, Any]:
    """Cancel a pending or processing order for a customer.

    Only orders with status 'pending' or 'processing' can be cancelled.
    Orders that have already shipped or been delivered cannot be cancelled
    (the customer must initiate a return instead).
    Always pass the customer_id from the session context so ownership is verified.
    Returns an access-denied error if the order does not belong to this customer.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("orders")
            .select("id, status, customer_id, total_amount")
            .eq("id", order_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        if not result.data:
            logger.warning(
                "cancel_order: order %s not found for customer %s",
                order_id, customer_id,
            )
            return {
                "success": False,
                "order_id": order_id,
                "unauthorized": True,
                "error": "Order not found or does not belong to your account.",
            }

        order = result.data[0]
        cancellable_statuses = {"pending", "processing"}
        if order["status"] not in cancellable_statuses:
            return {
                "success": False,
                "order_id": order_id,
                "current_status": order["status"],
                "error": (
                    f"Order cannot be cancelled because its status is '{order['status']}'. "
                    "Only pending or processing orders can be cancelled. "
                    "If the order has shipped, please initiate a return instead."
                ),
            }

        from datetime import datetime, timezone
        client.table("orders").update({
            "status": "cancelled",
        }).eq("id", order_id).execute()

        logger.info("Order %s cancelled for customer %s — reason: %s", order_id, customer_id, reason)
        return {
            "success": True,
            "order_id": order_id,
            "previous_status": order["status"],
            "new_status": "cancelled",
            "total_amount": order.get("total_amount", 0),
            "message": (
                f"Order {order_id} has been successfully cancelled. "
                "If payment was already captured, a full refund will be issued within 3-5 business days."
            ),
        }
    except Exception as exc:
        logger.error("cancel_order failed for %s: %s", order_id, exc)
        return {"success": False, "order_id": order_id, "error": str(exc)}


@tool
def get_carrier_tracking(order_id: str, customer_id: str) -> dict[str, Any]:
    """Fetch enriched live carrier tracking status for a shipped order.

    Simulates a live carrier API call to return the latest tracking event,
    current location, estimated delivery window, and number of transit stops.
    Only works for orders with a tracking number and status 'shipped'.
    Always pass the customer_id from the session context so ownership is verified.
    Returns an access-denied error if the order does not belong to this customer.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("orders")
            .select("id, status, carrier, tracking_number, estimated_delivery, shipped_at, customer_id")
            .eq("id", order_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        if not result.data:
            logger.warning(
                "get_carrier_tracking: order %s not found for customer %s",
                order_id, customer_id,
            )
            return {
                "success": False,
                "order_id": order_id,
                "unauthorized": True,
                "error": "Order not found or does not belong to your account.",
            }

        order = result.data[0]
        tracking_number = order.get("tracking_number")
        carrier = order.get("carrier")

        if not tracking_number:
            return {
                "success": False,
                "order_id": order_id,
                "status": order["status"],
                "error": "No tracking number available yet. The order may still be processing.",
            }

        # Simulate carrier API enrichment based on order status
        carrier_events = {
            "shipped": [
                {"timestamp": order.get("shipped_at", "")[:16], "event": "Package picked up by carrier", "location": "Fulfillment Center, TX"},
                {"timestamp": "", "event": "In transit", "location": "Regional Sort Facility"},
                {"timestamp": "", "event": "Out for delivery", "location": "Local Delivery Hub"},
            ],
            "delivered": [
                {"timestamp": order.get("shipped_at", "")[:16], "event": "Package picked up by carrier", "location": "Fulfillment Center, TX"},
                {"timestamp": "", "event": "Delivered", "location": "Front door"},
            ],
        }

        status = order["status"]
        events = carrier_events.get(status, [{"event": f"Status: {status}", "location": "N/A"}])
        latest_event = events[-1]

        return {
            "success": True,
            "order_id": order_id,
            "carrier": carrier,
            "tracking_number": tracking_number,
            "order_status": status,
            "latest_event": latest_event["event"],
            "current_location": latest_event["location"],
            "estimated_delivery": order.get("estimated_delivery", "")[:10],
            "tracking_url": f"https://track.{(carrier or 'carrier').lower().replace(' ', '')}.com/{tracking_number}",
            "events": events,
        }
    except Exception as exc:
        logger.error("get_carrier_tracking failed for %s: %s", order_id, exc)
        return {"success": False, "order_id": order_id, "error": str(exc)}
