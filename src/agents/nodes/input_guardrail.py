"""Input guardrail node: validates user input before any LLM call.

Runs as the very first node in the graph (START → input_guardrail → router).
Appears as its own span in LangSmith so injection attempts, blocked messages,
and pass-through rates are all visible and traceable independently of the router.
"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.state import AgentState
from src.guardrails.validators import validate_input

logger = logging.getLogger(__name__)


def input_guardrail_node(state: AgentState) -> AgentState:
    """Validate user input for length and prompt injection before routing.

    If the input is unsafe the graph short-circuits: final_response is set,
    guardrail_input_blocked=True, and the conditional edge routes directly to END
    without touching any LLM or database tool.

    If the input is safe, the node is a transparent pass-through and
    guardrail_input_blocked=False — the graph continues to the router.

    LangSmith records this as a separate node span with:
      - input: the raw user message
      - output: blocked=True/False, reason (if blocked)
    """
    messages = state.get("messages", [])
    user_text = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_text = str(msg.content)
            break

    result = validate_input(user_text)

    if not result.safe:
        logger.warning(
            "Input guardrail BLOCKED for customer %s | reason: %s | text: %.80s",
            state.get("customer_id"),
            result.reason,
            user_text,
        )
        denial = result.reason or "I can only help with order tracking, returns, and refunds."
        return {
            **state,
            "intent": "harmful",
            "guardrail_input_blocked": True,
            "final_response": denial,
            "messages": messages + [AIMessage(content=denial)],
            "wants_ticket": False,
        }

    logger.info(
        "Input guardrail passed for customer %s | text: %.80s",
        state.get("customer_id"),
        user_text,
    )
    return {**state, "guardrail_input_blocked": False}
