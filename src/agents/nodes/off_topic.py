"""Off-topic node: politely declines requests outside e-commerce support scope."""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.state import AgentState
from src.config import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_OFF_TOPIC = """ROLE: You are a polite e-commerce customer support assistant.

TASK: The customer has asked something outside your scope. Decline naturally and redirect.

RULES:
  1. Acknowledge what they asked in a friendly, non-judgmental way (one clause).
  2. Clearly but gently state you can only help with: order tracking, returns, refunds, and delivery.
  3. Invite them to ask about any of those topics.
  4. 2-3 sentences maximum. Conversational tone, no bullet points.
  5. Do NOT lecture or over-explain. Do NOT apologise excessively.
"""

_SYSTEM_PROMPT_HARMFUL = """ROLE: You are a firm but professional e-commerce customer support assistant.

TASK: The customer has made a request you cannot assist with. Decline clearly and redirect.

RULES:
  1. Decline briefly and firmly without explaining why in detail.
  2. Redirect to your actual scope: order tracking, returns, refunds, and delivery.
  3. 1-2 sentences. Professional tone, no anger or judgment.
"""

_FALLBACK_OFF_TOPIC = (
    "I'm here to help with your shopping experience — things like order tracking, "
    "returns, refunds, and delivery questions. "
    "Do you have any questions about an order or a return?"
)

_FALLBACK_HARMFUL = (
    "I'm not able to help with that request. "
    "I'm a customer support assistant for order tracking, returns, and refunds. "
    "Is there anything I can help you with regarding your orders?"
)


def off_topic_node(state: AgentState) -> AgentState:
    """Generate a contextual LLM refusal for out-of-scope or harmful requests."""
    intent = state.get("intent", "off_topic")
    is_harmful = intent == "harmful"

    # Get the user's actual message to make the refusal contextual
    user_text = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_text = str(msg.content)
            break

    system_prompt = _SYSTEM_PROMPT_HARMFUL if is_harmful else _SYSTEM_PROMPT_OFF_TOPIC
    fallback = _FALLBACK_HARMFUL if is_harmful else _FALLBACK_OFF_TOPIC

    try:
        llm = get_llm("off_topic")
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_text or "(no message)"),
        ])
        message = response.content or fallback
    except Exception as exc:
        logger.error("Off-topic LLM call failed: %s — using fallback", exc)
        message = fallback

    logger.info(
        "Off-topic request blocked (intent=%s) for customer %s",
        intent,
        state.get("customer_id"),
    )

    return {
        **state,
        "final_response": message,
        "messages": state.get("messages", []) + [AIMessage(content=message)],
    }
