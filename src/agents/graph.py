"""Main LangGraph StateGraph definition for the customer support agent."""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.nodes.cancellations import cancellations_node
from src.agents.nodes.escalation import escalation_node
from src.agents.nodes.input_guardrail import input_guardrail_node
from src.agents.nodes.off_topic import off_topic_node
from src.agents.nodes.output_guardrail import output_guardrail_node
from src.agents.nodes.refunds import refunds_node
from src.agents.nodes.responder import responder_node
from src.agents.nodes.returns import returns_node
from src.agents.nodes.router import router_node
from src.agents.nodes.wismo import wismo_node
from src.agents.state import AgentState
from src.config import get_settings

logger = logging.getLogger(__name__)


def _route_after_input_guardrail(state: AgentState) -> str:
    """Route to END if input was blocked by the guardrail, otherwise continue to router."""
    if state.get("guardrail_input_blocked"):
        return END
    return "router"


def _route_by_intent(state: AgentState) -> str:
    """Conditional edge: route to the appropriate node based on classified intent."""
    settings = get_settings()
    intent = state.get("intent", "other")
    error_count = state.get("tool_error_count", 0)
    customer_profile = state.get("customer_profile") or {}

    # Auto-escalation conditions
    if error_count >= settings.max_auto_retries:
        logger.warning("Auto-escalating: max retries (%d) reached", error_count)
        return "escalation"

    fraud_score = customer_profile.get("fraud_score", 0.0)
    if fraud_score > settings.fraud_score_threshold:
        logger.warning("Auto-escalating: fraud score %.2f exceeds threshold", fraud_score)
        return "escalation"

    route_map = {
        "wismo": "wismo",
        "return": "returns",
        "refund": "refunds",
        "cancel": "cancellations",
        "escalate": "escalation",
        "off_topic": "off_topic",
        "harmful": "off_topic",
        "other": "responder",
    }
    return route_map.get(intent, "responder")


def _route_returns(state: AgentState) -> str:
    """Conditional edge after returns_node: route to rma or responder."""
    eligibility = state.get("return_eligibility") or {}
    if eligibility.get("eligible"):
        # RMA is already created inside returns_node; go directly to responder
        return "responder"
    return "responder"


def _check_escalation_needed(state: AgentState) -> str:
    """After customer profile is loaded (pre-routing), check VIP + escalation conditions."""
    settings = get_settings()
    customer_profile = state.get("customer_profile") or {}

    fraud_score = customer_profile.get("fraud_score", 0.0)
    if fraud_score > settings.fraud_score_threshold:
        return "escalation"

    return "route"


def build_graph() -> Any:
    """Build and compile the LangGraph StateGraph."""
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("input_guardrail", input_guardrail_node)
    graph.add_node("router", router_node)
    graph.add_node("wismo", wismo_node)
    graph.add_node("returns", returns_node)
    graph.add_node("refunds", refunds_node)
    graph.add_node("cancellations", cancellations_node)
    graph.add_node("escalation", escalation_node)
    graph.add_node("responder", responder_node)
    graph.add_node("output_guardrail", output_guardrail_node)
    graph.add_node("off_topic", off_topic_node)

    # Entry: START → input_guardrail
    graph.add_edge(START, "input_guardrail")

    # input_guardrail → END (if blocked) or → router (if safe)
    graph.add_conditional_edges(
        "input_guardrail",
        _route_after_input_guardrail,
        {END: END, "router": "router"},
    )

    # Router conditional edges
    graph.add_conditional_edges(
        "router",
        _route_by_intent,
        {
            "wismo": "wismo",
            "returns": "returns",
            "refunds": "refunds",
            "escalation": "escalation",
            "off_topic": "off_topic",
            "responder": "responder",
        },
    )

    # wismo → responder → output_guardrail → END
    graph.add_edge("wismo", "responder")

    # returns → responder (RMA created inside returns node if eligible)
    graph.add_edge("returns", "responder")

    # refunds → responder → output_guardrail → END
    graph.add_edge("refunds", "responder")

    # cancellations → output_guardrail → END (response already composed inside the node)
    graph.add_edge("cancellations", "output_guardrail")

    # responder → output_guardrail → END
    graph.add_edge("responder", "output_guardrail")
    graph.add_edge("output_guardrail", END)

    # escalation → END
    graph.add_edge("escalation", END)

    # off_topic/harmful → END
    graph.add_edge("off_topic", END)

    return graph.compile()


# Singleton compiled graph
_compiled_graph: Any = None


def get_graph() -> Any:
    """Return the singleton compiled graph."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
        logger.info("LangGraph compiled successfully.")
    return _compiled_graph
