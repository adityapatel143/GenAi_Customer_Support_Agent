import logging
from typing import Any

from langchain_core.tools import tool

from src.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


@tool
def get_customer_profile(customer_id: str) -> dict[str, Any]:
    """Get the full profile of a customer including VIP status and fraud score.

    Returns the customer's name, email, is_vip flag, fraud_score (0.0 to 1.0),
    and account creation date. Use this at the start of any interaction to check
    for special handling (VIP escalation, fraud risk flagging).
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("customers")
            .select("*")
            .eq("id", customer_id)
            .single()
            .execute()
        )
        if not result.data:
            return {"error": f"Customer {customer_id} not found", "customer_id": customer_id}
        return {"success": True, **result.data}
    except Exception as exc:
        logger.error("get_customer_profile failed for %s: %s", customer_id, exc)
        return {"error": str(exc), "customer_id": customer_id}


@tool
def flag_fraud_risk(customer_id: str, reason: str) -> dict[str, Any]:
    """Flag a customer as having elevated fraud risk by updating their fraud_score.

    Sets the customer's fraud_score to 0.9 and logs the reason. Use this when
    suspicious patterns are detected (e.g., repeated return abuse, suspicious order
    patterns). This will trigger automatic escalation for future interactions.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("customers")
            .update({"fraud_score": 0.9})
            .eq("id", customer_id)
            .execute()
        )
        if not result.data:
            return {"success": False, "error": f"Customer {customer_id} not found"}

        logger.warning("Fraud risk flagged for customer %s: %s", customer_id, reason)
        return {
            "success": True,
            "customer_id": customer_id,
            "fraud_score": 0.9,
            "reason": reason,
            "message": "Customer flagged for fraud risk review.",
        }
    except Exception as exc:
        logger.error("flag_fraud_risk failed for %s: %s", customer_id, exc)
        return {"success": False, "error": str(exc), "customer_id": customer_id}
