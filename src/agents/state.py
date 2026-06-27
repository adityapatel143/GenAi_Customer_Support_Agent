from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict


class AgentState(TypedDict):
    messages: list[BaseMessage]
    customer_id: str | None
    order_id: str | None
    return_id: str | None       # RET-XXX extracted from user message (existing return lookup)
    intent: str | None          # "wismo" | "return" | "refund" | "other" | "escalate"
    customer_profile: dict[str, Any] | None
    order_data: dict[str, Any] | None
    return_eligibility: dict[str, Any] | None
    rma_data: dict[str, Any] | None
    ticket_id: str | None
    escalation_reason: str | None
    final_response: str | None
    requires_human: bool
    tool_error_count: int        # tracks consecutive tool errors for auto-escalation
    tool_calls_made: list[str]   # tracks tool names called this session (for UI expander)
    wants_ticket: bool           # True when user explicitly asks to open a support ticket
    orders_list: list            # populated by get_customer_orders (order history)
    order_access_denied: bool    # True when requested order does not belong to this customer
    refund_status: dict | None   # populated by check_refund_status in refunds node
    cancellation_status: dict | None  # populated by cancellations_node
    store_credit_applied: dict | None  # populated by escalation_node when credit issued
    notification_sent: bool      # True when send_customer_notification succeeded this turn
    guardrail_input_blocked: bool  # True when input_guardrail blocked the message
    guardrail_output_passed: bool  # True when output_guardrail validated the response
    ticket_history_requested: bool  # True when user asks to see ticket history
