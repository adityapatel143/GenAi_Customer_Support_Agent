"""Router node: classifies user intent from the conversation."""
from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.state import AgentState
from src.config import get_llm
from src.guardrails.validators import ALLOWED_INTENTS

logger = logging.getLogger(__name__)

# Keywords that indicate the user wants to open / create a support ticket
_TICKET_KEYWORDS = [
    "open a ticket", "open ticket", "create a ticket", "create ticket",
    "raise a ticket", "raise ticket", "log a ticket", "log ticket",
    "file a ticket", "submit a ticket", "open a case", "create a case",
    "raise a complaint", "file a complaint", "log a complaint",
    "i want to open", "i want to raise", "i want to create a ticket",
    "new ticket", "new support ticket", "support ticket", "support request",
    "submit a request", "submit a case", "open a support case",
    "i need a ticket", "can you open a ticket", "please open a ticket",
    "i'd like to open", "i would like to open a ticket",
    "need to raise a ticket", "need to file a complaint",
    "start a ticket", "lodge a complaint", "lodge a ticket",
    "report an issue", "report a problem",
]

# Keywords that indicate a ticket STATUS inquiry — route as 'other' (no LLM needed)
_TICKET_STATUS_KEYWORDS = [
    "status of my ticket", "ticket status", "check my ticket",
    "update on my ticket", "update on ticket", "what is my ticket",
    "what's my ticket", "ticket update", "case status", "case update",
    "my case status", "check my case", "tkt-",
]

# Keywords that indicate the user wants to list ALL their tickets
_TICKET_HISTORY_KEYWORDS = [
    "my tickets", "all my tickets", "show my tickets", "show me my tickets",
    "list my tickets", "all tickets", "ticket history", "my support tickets",
    "my cases", "all my cases", "show my cases", "list my cases",
    "view my tickets", "see my tickets", "check all my tickets",
    "tickets and status", "ticket and status",
]


_HARMFUL_KEYWORDS = [
    "bomb", "explosive", "weapon", "poison", "hack", "malware", "ransomware",
    "how to kill", "how to attack", "drug synthesis", "synthesize drugs",
    "child pornography", "csam", "terrorism", "suicide method",
]

# Keywords that indicate clearly off-topic requests (not harmful, just out of scope)
_OFF_TOPIC_KEYWORDS = [
    "write code", "write a program", "write me a", "generate code",
    "debug my code", "homework", "essay", "recipe", "weather",
    "tell me a joke", "who are you", "what is your name",
    "stock price", "sports score", "translate", "math problem",
    "medical advice", "legal advice", "investment advice",
]


def _pre_filter(text: str) -> str | None:
    """Check text against keyword lists before calling the LLM.

    Returns 'harmful', 'off_topic', 'other', or None (meaning pass through to LLM).
    """
    lower = text.lower()
    if any(kw in lower for kw in _HARMFUL_KEYWORDS):
        return "harmful"
    if any(kw in lower for kw in _TICKET_HISTORY_KEYWORDS):
        return "ticket_history"
    if any(kw in lower for kw in _TICKET_STATUS_KEYWORDS):
        return "other"
    if any(kw in lower for kw in _OFF_TOPIC_KEYWORDS):
        return "off_topic"
    return None


_SYSTEM_PROMPT = """ROLE: You are a precise intent classifier for an e-commerce customer support system.

TASK: Analyze the customer message and output a single JSON object classifying the intent.

OUTPUT SCHEMA:
{
  "intent": "<one of the values listed below>",
  "order_id": "<ORD-XXXX if explicitly mentioned, else null>",
  "return_id": "<RET-XXXX if explicitly mentioned, else null>"
}

INTENT DEFINITIONS:
  "wismo"     : Customer asks about order location, shipping status, tracking, delivery, OR wants to view/list their order history, past orders, recent purchases, or any order-related lookup
  "return"    : Customer wants to return an item or initiate a return / exchange
  "refund"    : Customer asks about a refund, its status, or wants money back
  "cancel"    : Customer wants to cancel an order that has not yet shipped
  "escalate"  : Customer is angry, frustrated, or explicitly demands a manager / human agent
  "off_topic" : Request is unrelated to e-commerce (coding, recipes, weather, general knowledge)
  "harmful"   : Request involves dangerous, illegal, or harmful content
  "other"     : Any query about orders/shopping that does not clearly fit the above categories.
               This includes: ticket status enquiries, general account questions, payment questions,
               delivery address changes, or anything support-related that is not wismo/return/refund/cancel.

RULES:
  1. Output ONLY the raw JSON object — no explanation, no markdown, no extra text.
  2. "return" and "refund" are distinct intents: "return" = sending item back or checking a return status; "refund" = getting money back.
  3. "cancel" means stopping an unshipped order. Do NOT classify as "return" when the customer wants to cancel.
  4. If a customer mentions both return and refund, choose the primary stated goal.
  5. Extract order_id ONLY when it appears in the exact format ORD-XXXX.
  6. Extract return_id ONLY when it appears in the exact format RET-XXXX (e.g. RET-003, RET-001).
  7. When a customer asks about the status of a RET-XXXX, classify as "return" and populate return_id.
  8. Never infer or guess an order_id or return_id from context.
  9. NEVER include a customer_id field — customer identity is determined by the authenticated session.

EXAMPLES:

# --- wismo: order status & tracking ---
{"input": "Where is my order ORD-1042?",                                    "output": {"intent": "wismo",    "order_id": "ORD-1042"}}
{"input": "What's the status of ORD-2201?",                                 "output": {"intent": "wismo",    "order_id": "ORD-2201"}}
{"input": "Has my order shipped yet?",                                       "output": {"intent": "wismo",    "order_id": null}}
{"input": "When will my order arrive?",                                      "output": {"intent": "wismo",    "order_id": null}}
{"input": "Can you track my package?",                                       "output": {"intent": "wismo",    "order_id": null}}
{"input": "What's the tracking number for my order?",                        "output": {"intent": "wismo",    "order_id": null}}
{"input": "My order is showing as processing, when will it ship?",           "output": {"intent": "wismo",    "order_id": null}}
{"input": "I haven't received my package yet",                               "output": {"intent": "wismo",    "order_id": null}}
{"input": "My delivery is late",                                             "output": {"intent": "wismo",    "order_id": null}}
{"input": "The carrier says delivered but I didn't get anything",            "output": {"intent": "wismo",    "order_id": null}}
{"input": "Show me all my orders",                                           "output": {"intent": "wismo",    "order_id": null}}
{"input": "Show me my order history",                                        "output": {"intent": "wismo",    "order_id": null}}
{"input": "What are my past orders?",                                        "output": {"intent": "wismo",    "order_id": null}}
{"input": "Can I see my recent purchases?",                                  "output": {"intent": "wismo",    "order_id": null}}
{"input": "List my old orders",                                              "output": {"intent": "wismo",    "order_id": null}}
{"input": "I want to see all my previous orders",                            "output": {"intent": "wismo",    "order_id": null}}
{"input": "What did I order last month?",                                    "output": {"intent": "wismo",    "order_id": null}}

# --- return (initiate) ---
{"input": "I want to return the shoes I bought, they don't fit",             "output": {"intent": "return",   "order_id": null,       "return_id": null}}
{"input": "My item arrived damaged, can I send it back?",                    "output": {"intent": "return",   "order_id": null,       "return_id": null}}
{"input": "How do I return something?",                                      "output": {"intent": "return",   "order_id": null,       "return_id": null}}
{"input": "I'd like to initiate a return for ORD-3310",                      "output": {"intent": "return",   "order_id": "ORD-3310", "return_id": null}}
{"input": "The product is defective, I want to send it back",                "output": {"intent": "return",   "order_id": null,       "return_id": null}}
{"input": "I changed my mind and want to return the item",                   "output": {"intent": "return",   "order_id": null,       "return_id": null}}
{"input": "Can I exchange this for a different size?",                       "output": {"intent": "return",   "order_id": null,       "return_id": null}}
{"input": "I received the wrong item, I want to return it",                  "output": {"intent": "return",   "order_id": null,       "return_id": null}}
{"input": "I want to send back my purchase",                                 "output": {"intent": "return",   "order_id": null,       "return_id": null}}
{"input": "Start a return for my last order",                                "output": {"intent": "return",   "order_id": null,       "return_id": null}}

# --- return (status of existing return) ---
{"input": "Can you show the status of RET-003?",                             "output": {"intent": "return",   "order_id": null,       "return_id": "RET-003"}}
{"input": "What is the status of my return RET-001?",                        "output": {"intent": "return",   "order_id": null,       "return_id": "RET-001"}}
{"input": "Where is my return request RET-005?",                             "output": {"intent": "return",   "order_id": null,       "return_id": "RET-005"}}
{"input": "Update on RET-002",                                               "output": {"intent": "return",   "order_id": null,       "return_id": "RET-002"}}
{"input": "Has my return RET-004 been approved?",                            "output": {"intent": "return",   "order_id": null,       "return_id": "RET-004"}}

# --- refund ---
{"input": "I haven't received my refund for ORD-0998",                       "output": {"intent": "refund",   "order_id": "ORD-0998"}}
{"input": "When will I get my money back?",                                  "output": {"intent": "refund",   "order_id": null}}
{"input": "I want a refund",                                                 "output": {"intent": "refund",   "order_id": null}}
{"input": "What is the status of my refund?",                                "output": {"intent": "refund",   "order_id": null}}
{"input": "My refund hasn't hit my account yet",                             "output": {"intent": "refund",   "order_id": null}}
{"input": "I was charged twice, please refund the extra amount",             "output": {"intent": "refund",   "order_id": null}}
{"input": "I returned the item two weeks ago, still no refund",              "output": {"intent": "refund",   "order_id": null}}
{"input": "Can I get a partial refund for the damaged item?",                "output": {"intent": "refund",   "order_id": null}}
{"input": "Please process a refund to my credit card",                       "output": {"intent": "refund",   "order_id": null}}

# --- cancel ---
{"input": "I want to cancel my order ORD-5512",                              "output": {"intent": "cancel",   "order_id": "ORD-5512"}}
{"input": "Please cancel my order before it ships",                          "output": {"intent": "cancel",   "order_id": null}}
{"input": "I accidentally placed an order, can you cancel it?",              "output": {"intent": "cancel",   "order_id": null}}
{"input": "Stop my order, I don't want it anymore",                          "output": {"intent": "cancel",   "order_id": null}}
{"input": "Can I still cancel? It hasn't shipped yet",                       "output": {"intent": "cancel",   "order_id": null}}

# --- escalate ---
{"input": "This is outrageous! I want to speak to a manager NOW",            "output": {"intent": "escalate", "order_id": null}}
{"input": "I am extremely frustrated, connect me to a human agent",          "output": {"intent": "escalate", "order_id": null}}
{"input": "This is unacceptable! Get me your supervisor",                    "output": {"intent": "escalate", "order_id": null}}
{"input": "I've been waiting for weeks, this is ridiculous",                 "output": {"intent": "escalate", "order_id": null}}
{"input": "I want to file a formal complaint",                               "output": {"intent": "escalate", "order_id": null}}
{"input": "Your service is terrible, I demand a resolution",                 "output": {"intent": "escalate", "order_id": null}}
{"input": "I'm going to report this to my bank if you don't help me",        "output": {"intent": "escalate", "order_id": null}}
{"input": "Let me speak to someone who can actually help",                   "output": {"intent": "escalate", "order_id": null}}

# --- other (ticket open request handled separately by keyword pre-filter) ---
{"input": "What's the weather in Tokyo?",                                    "output": {"intent": "off_topic", "order_id": null}}
{"input": "I have an issue with my recent purchase",                         "output": {"intent": "other",    "order_id": null}}
{"input": "I have a question about my account",                              "output": {"intent": "other",    "order_id": null}}
{"input": "Can I change my delivery address?",                               "output": {"intent": "other",    "order_id": null}}
{"input": "I need help with my payment",                                     "output": {"intent": "other",    "order_id": null}}
"""


def router_node(state: AgentState) -> AgentState:
    """Classify intent from the latest user message and extract order/customer IDs.

    Input guardrail (injection check) already ran before this node.
    This node handles keyword pre-filtering and LLM-based classification.
    """
    messages = state.get("messages", [])
    user_text = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_text = str(msg.content)
            break

    # Pre-filter: catch obviously harmful/off-topic requests without an LLM call
    pre_result = _pre_filter(user_text)
    if pre_result:
        logger.info("Pre-filter classified request as '%s': %.80s", pre_result, user_text)
        if pre_result == "ticket_history":
            # User wants to list all their tickets — route to responder as 'other'
            # with a flag so the responder knows to call search_tickets.
            return {**state, "intent": "other", "ticket_history_requested": True, "wants_ticket": False}
        return {**state, "intent": pre_result, "wants_ticket": False}

    # Ticket-opening detection: fast keyword check, no LLM needed
    lower_text = user_text.lower()
    if any(kw in lower_text for kw in _TICKET_KEYWORDS):
        logger.info("Ticket-opening intent detected: %.80s", user_text)
        return {**state, "intent": state.get("intent") or "other", "wants_ticket": True}

    try:
        llm = get_llm("router")
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_text),
        ])

        raw = response.content or ""
        # Extract JSON from possible markdown fences
        json_str = raw.strip()
        if "```" in json_str:
            m = re.search(r"\{.*?\}", json_str, re.DOTALL)
            json_str = m.group(0) if m else json_str

        parsed = json.loads(json_str)
        intent = parsed.get("intent", "other")
        # Whitelist: reject any intent value not in the allowed set
        if intent not in ALLOWED_INTENTS:
            logger.warning("Router returned unknown intent '%s' — defaulting to 'other'", intent)
            intent = "other"
        order_id = parsed.get("order_id") or state.get("order_id")
        return_id = parsed.get("return_id") or state.get("return_id")
        # customer_id is ALWAYS taken from the authenticated session — never from LLM output.
        # This prevents a user from injecting another customer's ID in their message.
        customer_id = state.get("customer_id")

        logger.info("Router classified intent=%s, order_id=%s, return_id=%s", intent, order_id, return_id)

        return {
            **state,
            "intent": intent,
            "order_id": order_id if order_id != "null" else state.get("order_id"),
            "return_id": return_id if return_id != "null" else state.get("return_id"),
            "customer_id": customer_id,
            "wants_ticket": False,
        }

    except Exception as exc:
        logger.error("Router node failed: %s", exc)
        return {
            **state,
            "intent": "other",
            "tool_error_count": state.get("tool_error_count", 0) + 1,
            "wants_ticket": False,
        }
