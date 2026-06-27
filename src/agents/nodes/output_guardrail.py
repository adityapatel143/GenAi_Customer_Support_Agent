"""Output guardrail node: sanitises the LLM response before it reaches the customer.

Runs as the last node before END (responder → output_guardrail → END).
Appears as its own span in LangSmith so PII redactions, toxic blocks, factual
inconsistencies, and access-denied containment events are all independently
visible and traceable.
"""
from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage

from src.agents.state import AgentState
from src.guardrails.validators import validate_response

logger = logging.getLogger(__name__)


def output_guardrail_node(state: AgentState) -> AgentState:
    """Validate and sanitise the responder's output before it is shown to the customer.

    Pipeline (in order):
      1. PII redaction  — strips SSNs and credit card numbers
      2. Toxic language — replaces response with safe fallback if toxic content found
      3. Factual consistency — logs inconsistencies (single-order context only)
      4. Access-denied containment — replaces response if forbidden order data leaks

    Returns updated final_response (and AIMessage) if any cleaning was applied.

    LangSmith records this as a separate node span with:
      - input:  raw final_response from responder
      - output: cleaned final_response, guardrail_output_passed flag, failures list
    """
    raw = state.get("final_response") or ""
    order_data = state.get("order_data") or {}
    order_access_denied = state.get("order_access_denied", False)
    messages = list(state.get("messages", []))

    # Fact-check only for single-order context.
    # Multi-order history responses contain multiple amounts/tracking numbers —
    # checking against a single order would produce false positives.
    fact_check_data = order_data if order_data else None

    validation = validate_response(raw, fact_check_data)
    cleaned = validation.output

    if not validation.passed:
        logger.warning(
            "Output guardrail failures for customer %s: %s",
            state.get("customer_id"),
            validation.failures,
        )
    else:
        logger.info(
            "Output guardrail passed for customer %s",
            state.get("customer_id"),
        )

    # Access-denied containment: if the order does not belong to this customer,
    # verify the response does not leak the forbidden order ID or a tracking number.
    if order_access_denied:
        forbidden_order = state.get("order_id", "")
        tracking_re = re.compile(r"\b([A-Z]{2,5}\d{8,}|\d{12,22})\b")
        if (forbidden_order and forbidden_order in cleaned) or tracking_re.search(cleaned):
            logger.warning(
                "Output guardrail ACCESS-DENIED containment triggered for customer %s "
                "— forbidden order data detected in response, replacing with safe denial",
                state.get("customer_id"),
            )
            cleaned = (
                "I wasn't able to find an order with that ID on your account. "
                "Please double-check the order ID and try again."
            )

    # If content changed, replace the last AIMessage so messages list stays consistent
    if cleaned != raw:
        messages = [
            m for m in messages
            if not (isinstance(m, AIMessage) and m.content == raw)
        ]
        messages.append(AIMessage(content=cleaned))

    return {
        **state,
        "final_response": cleaned,
        "messages": messages,
        "guardrail_output_passed": validation.passed,
    }
