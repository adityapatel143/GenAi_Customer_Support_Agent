"""Streamlit entry point for the AI Customer Support Agent."""
from __future__ import annotations

import logging
import time
from typing import Any

import streamlit as st
from langchain_core.messages import HumanMessage

from src.agents.graph import get_graph
from src.agents.state import AgentState
from src.config import configure_logging, get_settings
from src.observability.langsmith_client import (
    create_trace,
    get_trace_url,
    log_event,
    log_score,
)
from src.human_dashboard.queue import render_human_queue
from src.tools.customer_tools import get_customer_profile
from src.tools.ticket_tools import create_ticket
from src.utils.export import chat_history_as_pdf, chat_history_as_txt

configure_logging(get_settings())
logger = logging.getLogger(__name__)

settings = get_settings()
st.set_page_config(
    page_title=settings.app_title,
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_ticket_history(customer_id: str) -> list[dict[str, Any]]:
    """Fetch ticket history for a customer from Supabase."""
    try:
        from src.database.supabase_client import get_supabase_client
        db = get_supabase_client()
        result = (
            db.table("tickets")
            .select("id, intent, status, priority, created_at")
            .eq("customer_id", customer_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("Could not fetch ticket history: %s", exc)
        return []


def _status_badge(status: str) -> str:
    colors = {
        "open": "🟡",
        "in_progress": "🔵",
        "escalated": "🔴",
        "resolved": "🟢",
        "closed": "⚫",
    }
    return colors.get(status, "⚪") + f" {status.upper()}"


def _priority_badge(priority: str) -> str:
    colors = {
        "low": "🟢",
        "normal": "🔵",
        "high": "🟠",
        "urgent": "🔴",
    }
    return colors.get(priority, "⚪") + f" {priority.upper()}"


def _init_session_state() -> None:
    defaults: dict[str, Any] = {
        "agent_state": None,
        "trace": None,
        "trace_url": None,
        "session_start": None,
        "chat_history": [],  # list of {"role": str, "content": str}
        "tool_calls": [],
        "current_ticket_id": None,
        "customer_profile": None,
        "show_ticket_form": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _resolve_current_ticket() -> None:
    """Mark the active ticket as resolved before ending the session."""
    ticket_id = st.session_state.get("current_ticket_id")
    if not ticket_id:
        return
    try:
        from src.tools.ticket_tools import update_ticket
        update_ticket.invoke({
            "ticket_id": ticket_id,
            "status": "resolved",
            "resolved_by": "agent",
        })
        logger.info("Ticket %s resolved on session close.", ticket_id)
    except Exception as exc:
        logger.warning("Could not resolve ticket %s: %s", ticket_id, exc)


def _reset_session() -> None:
    for key in ["agent_state", "trace", "trace_url", "session_start",
                "chat_history", "tool_calls", "current_ticket_id"]:
        st.session_state[key] = None if key != "chat_history" and key != "tool_calls" else []
    st.session_state["show_ticket_form"] = False


def _inject_css() -> None:
    """Inject custom CSS for a polished chat interface."""
    st.markdown(
        """
<style>
/* ── Hero banner ─────────────────────────────────────────── */
.support-hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 18px;
    padding: 2rem 2.5rem;
    color: #fff;
    margin-bottom: 1.5rem;
    box-shadow: 0 8px 32px rgba(15, 52, 96, 0.35);
    position: relative;
    overflow: hidden;
}
.support-hero::after {
    content: '';
    position: absolute;
    top: -60px;
    right: -40px;
    width: 260px;
    height: 260px;
    background: radial-gradient(circle, rgba(102, 126, 234, 0.35) 0%, transparent 70%);
    pointer-events: none;
}
.support-hero h1 {
    margin: 0 0 0.3rem;
    font-size: 1.9rem;
    font-weight: 800;
    letter-spacing: -0.5px;
}
.support-hero p {
    margin: 0;
    opacity: 0.75;
    font-size: 0.95rem;
}
.hero-pills { margin-top: 1rem; }
.hero-pill {
    display: inline-block;
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 20px;
    padding: 3px 12px;
    margin-right: 6px;
    margin-bottom: 4px;
    font-size: 0.76rem;
    color: rgba(255, 255, 255, 0.9);
    letter-spacing: 0.3px;
}

/* ── Escalation banner ───────────────────────────────────── */
.escalation-banner {
    background: rgba(229, 62, 62, 0.08);
    border: 1px solid rgba(229, 62, 62, 0.35);
    border-radius: 12px;
    padding: 1rem 1.4rem;
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 14px;
    color: #c53030;
}
.escalation-banner .esc-icon { font-size: 1.8rem; line-height: 1; }
.escalation-banner .esc-title { font-weight: 700; font-size: 1rem; }
.escalation-banner .esc-sub { font-size: 0.83rem; opacity: 0.8; margin-top: 2px; }

/* ── Ticket bar ──────────────────────────────────────────── */
.ticket-bar {
    background: rgba(66, 153, 225, 0.07);
    border: 1px solid rgba(66, 153, 225, 0.28);
    border-radius: 10px;
    padding: 0.65rem 1.1rem;
    margin-bottom: 0.5rem;
    font-size: 0.88rem;
    color: #2b6cb0;
}

/* ── Tool chips ──────────────────────────────────────────── */
.tool-chip {
    display: inline-block;
    background: rgba(102, 126, 234, 0.1);
    border: 1px solid rgba(102, 126, 234, 0.25);
    border-radius: 20px;
    padding: 3px 12px;
    margin: 3px 4px;
    font-size: 0.78rem;
    font-family: monospace;
    color: #553c9a;
}

/* ── Profile card ────────────────────────────────────────── */
.profile-card {
    background: linear-gradient(135deg, #ebf4ff 0%, #e8f0fe 100%);
    border: 1px solid #c3d8f5;
    border-radius: 14px;
    padding: 1rem 1.2rem;
    margin-top: 0.5rem;
}
.profile-name {
    font-size: 1.05rem;
    font-weight: 700;
    color: #1a202c;
}
.profile-email {
    font-size: 0.8rem;
    color: #4a5568;
    margin: 3px 0 8px;
}
.vip-badge {
    display: inline-block;
    background: linear-gradient(135deg, #f6d365, #fda085);
    color: #744210;
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.4px;
}
.std-badge {
    display: inline-block;
    background: #e2e8f0;
    color: #4a5568;
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 0.7rem;
    font-weight: 600;
}

/* ── Empty state ─────────────────────────────────────────── */
.empty-state {
    text-align: center;
    padding: 4rem 2rem 5rem;
    color: #718096;
}
.empty-state .big-icon {
    font-size: 4.5rem;
    line-height: 1;
    display: block;
    margin-bottom: 1rem;
}
.empty-state h3 {
    font-size: 1.35rem;
    font-weight: 700;
    margin: 0 0 0.5rem;
    color: #4a5568;
}
.empty-state p {
    font-size: 0.93rem;
    opacity: 0.75;
    max-width: 360px;
    margin: 0 auto;
    line-height: 1.6;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _render_customer_chat() -> None:
    """Render the customer-facing AI chat interface."""
    profile = st.session_state.get("customer_profile")
    customer_id = st.session_state.get("_customer_id_input", "")
    current_ticket_id = st.session_state.get("current_ticket_id")

    # ── Hero banner ────────────────────────────────────────────────────────────
    first_name = profile.get("name", "").split()[0] if profile and profile.get("name") else None
    heading = f"Welcome back, {first_name}! 👋" if first_name else f"🤖 {settings.app_title}"
    subtext = "How can we help you today?" if first_name else "AI-powered support, available 24/7"
    st.markdown(
        f"""<div class="support-hero">
  <h1>{heading}</h1>
  <p>{subtext}</p>
  <div class="hero-pills">
    <span class="hero-pill">⚡ AI-Powered</span>
    <span class="hero-pill">🔒 Secure &amp; Private</span>
    <span class="hero-pill">📦 Order Support</span>
    <span class="hero-pill">↩ Returns &amp; Refunds</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── Active ticket / escalation bar ─────────────────────────────────────────
    if current_ticket_id:
        agent_state: AgentState | None = st.session_state.get("agent_state")
        requires_human = agent_state.get("requires_human", False) if agent_state else False
        intent = agent_state.get("intent", "N/A") if agent_state else "N/A"

        if requires_human:
            st.markdown(
                f"""<div class="escalation-banner">
  <div class="esc-icon">🚨</div>
  <div>
    <div class="esc-title">Escalated to Human Agent</div>
    <div class="esc-sub">Ticket <strong>{current_ticket_id}</strong> &nbsp;&middot;&nbsp; Intent: {intent} &nbsp;&middot;&nbsp; A specialist will contact you shortly.</div>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
        else:
            col_info, col_close = st.columns([5, 1])
            with col_info:
                st.markdown(
                    f"""<div class="ticket-bar">📋 <strong>{current_ticket_id}</strong> &nbsp;&middot;&nbsp; Intent: <code>{intent}</code> &nbsp;&middot;&nbsp; 🔵 In Progress</div>""",
                    unsafe_allow_html=True,
                )
            with col_close:
                if st.button("✅ Close Ticket", use_container_width=True):
                    _resolve_current_ticket()
                    _reset_session()
                    st.success("Ticket resolved. Starting a new session.")
                    st.rerun()

    # ── Tool calls ─────────────────────────────────────────────────────────────
    tool_calls = st.session_state.get("tool_calls", [])
    if tool_calls:
        with st.expander(
            f"🔧 Tools used \u2014 {len(tool_calls)} call{'s' if len(tool_calls) > 1 else ''}",
            expanded=False,
        ):
            chips_html = "".join(
                f'<span class="tool-chip">&#9881; {tc}</span>' for tc in tool_calls
            )
            st.markdown(f'<div style="padding:4px 0">{chips_html}</div>', unsafe_allow_html=True)

    # Chat messages
    chat_history = st.session_state.get("chat_history", [])
    for msg in chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Guard: require customer ID
    if not customer_id:
        st.markdown(
            """<div class="empty-state">
  <span class="big-icon">💬</span>
  <h3>Welcome to Support</h3>
  <p>Enter your <strong>Customer ID</strong> in the sidebar to get started. Our AI agent can help with orders, returns, refunds, and more.</p>
</div>
""",
            unsafe_allow_html=True,
        )
        return

    # Inline ticket creation — only shown when the agent detected the user wants one
    if st.session_state.get("show_ticket_form") and not current_ticket_id:
        st.divider()
        with st.container(border=True):
            st.markdown("#### 📋 Open a Support Ticket")
            st.caption("This lets us track your issue and follow up if needed.")

            # Fetch past orders for the dropdown (cached in session state)
            if "_ticket_form_orders" not in st.session_state:
                try:
                    from src.tools.order_tools import get_customer_orders
                    _ord_result = get_customer_orders.invoke({"customer_id": customer_id})
                    st.session_state["_ticket_form_orders"] = [
                        o["id"] for o in (_ord_result.get("orders") or [])
                    ]
                except Exception:
                    st.session_state["_ticket_form_orders"] = []

            _past_orders: list[str] = st.session_state.get("_ticket_form_orders", [])

            if not _past_orders:
                st.warning("⚠️ No orders found on your account. An order is required to open a ticket. Please contact support if you believe this is an error.")
                if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_ticket"):
                    st.session_state["show_ticket_form"] = False
                    st.session_state.pop("_ticket_form_orders", None)
                    st.rerun()
            else:
                col_a, col_b = st.columns(2)
                with col_a:
                    _t_category = st.selectbox(
                        "Category",
                        ["General Inquiry", "Order Tracking", "Return Request", "Refund", "Other"],
                        key="ticket_form_category",
                    )
                with col_b:
                    _t_priority = st.selectbox(
                        "Priority",
                        ["normal", "low", "high", "urgent"],
                        key="ticket_form_priority",
                    )

                _t_order = st.selectbox(
                    "Order ID *",
                    options=["— Select an order —"] + _past_orders,
                    key="ticket_form_order",
                    help="Select the order this ticket is about. Required.",
                )

                _t_desc_raw: str = st.text_area(
                    "Describe your issue (optional, max 250 characters)",
                    key="ticket_form_desc",
                    max_chars=250,
                    height=100,
                    placeholder="e.g. My package hasn't arrived and the tracking hasn't updated in 5 days.",
                )
                _chars_used = len(_t_desc_raw)
                st.caption(f"{_chars_used} / 250 characters used")

                _order_selected = _t_order != "— Select an order —"

                _col_yes, _col_no = st.columns(2)
                with _col_yes:
                    if st.button(
                        "✅ Open Ticket",
                        use_container_width=True,
                        type="primary",
                        key="btn_create_ticket",
                        disabled=not _order_selected,
                    ):
                        if not _order_selected:
                            st.error("Please select an order before opening a ticket.")
                        else:
                            _cat_map = {
                                "Order Tracking": "wismo",
                                "Return Request": "return",
                                "Refund": "refund",
                                "General Inquiry": "other",
                                "Other": "other",
                            }
                            try:
                                _tr = create_ticket.invoke({
                                    "customer_id": customer_id,
                                    "order_id": _t_order,
                                    "intent": _cat_map.get(_t_category, "other"),
                                    "priority": _t_priority,
                                    "description": _t_desc_raw.strip() or None,
                                })
                                if _tr.get("success"):
                                    st.session_state["current_ticket_id"] = _tr["ticket_id"]
                                    st.session_state["show_ticket_form"] = False
                                    st.session_state.pop("_ticket_form_orders", None)
                                    st.rerun()
                                else:
                                    st.error("Failed to open ticket.")
                            except Exception as _exc:
                                st.error(f"Error: {_exc}")
                with _col_no:
                    if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_ticket"):
                        st.session_state["show_ticket_form"] = False
                        st.session_state.pop("_ticket_form_orders", None)
                        st.rerun()
        st.divider()

    # Chat input
    user_input = st.chat_input("How can we help you today?")
    if not user_input:
        return

    # Display user message
    with st.chat_message("user"):
        st.markdown(user_input)
    chat_history.append({"role": "user", "content": user_input})
    st.session_state["chat_history"] = chat_history

    # Build per-turn agent state.
    # Only carry forward conversational context (message history, customer identity, ticket).
    # All per-turn action fields are reset to defaults so errors / intent / order data from
    # a previous message never bleed into the current one.  This prevents tool_error_count
    # from accumulating across messages and triggering spurious auto-escalation.
    start_time = time.time()
    prev_state: AgentState = st.session_state.get("agent_state") or {}
    agent_state: AgentState = {
        # Carry over across messages
        "messages": prev_state.get("messages", []) + [HumanMessage(content=user_input)],
        "customer_id": customer_id,
        "customer_profile": profile,
        "ticket_id": current_ticket_id,
        # Reset every turn
        "order_id": None,
        "intent": None,
        "order_data": None,
        "orders_list": [],
        "order_access_denied": False,
        "return_eligibility": None,
        "rma_data": None,
        "refund_status": None,
        "escalation_reason": None,
        "final_response": None,
        "requires_human": False,
        "tool_error_count": 0,
        "tool_calls_made": [],
        "wants_ticket": False,
        "guardrail_input_blocked": False,
        "guardrail_output_passed": True,
        "ticket_history_requested": False,
        "cancellation_status": None,
        "store_credit_applied": None,
        "notification_sent": False,
    }
    # Create trace if this is a new session
    trace = st.session_state.get("trace")
    if trace is None:
        trace = create_trace(
            session_name="customer_support_session",
            customer_id=customer_id,
            ticket_id=current_ticket_id,
            intent=None,
        )
        st.session_state["trace"] = trace
        st.session_state["trace_url"] = get_trace_url(trace)
        st.session_state["session_start"] = start_time

    # Run the graph
    graph = get_graph()
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result_state: AgentState = graph.invoke(agent_state)

                # If the graph escalated but no ticket existed yet, auto-create one
                # so the human queue has something to act on.
                if result_state.get("requires_human") and not current_ticket_id:
                    try:
                        from src.tools.ticket_tools import escalate_ticket as _escalate_tool
                        _t = create_ticket.invoke({
                            "customer_id": customer_id,
                            "order_id": result_state.get("order_id"),
                            "intent": result_state.get("intent", "escalate"),
                            "priority": "urgent",
                        })
                        if _t.get("success"):
                            current_ticket_id = _t["ticket_id"]
                            st.session_state["current_ticket_id"] = current_ticket_id
                            result_state = {**result_state, "ticket_id": current_ticket_id}
                            _escalate_tool.invoke({
                                "ticket_id": current_ticket_id,
                                "reason": result_state.get("escalation_reason") or "Customer requested escalation",
                                "priority": "urgent",
                            })
                    except Exception as _exc:
                        logger.warning("Could not auto-create escalation ticket: %s", _exc)

                final_response = result_state.get("final_response") or "I'm sorry, I couldn't process your request. Please try again."
                st.markdown(final_response)

                # Update session state
                st.session_state["agent_state"] = result_state
                st.session_state["tool_calls"] = result_state.get("tool_calls_made", [])
                chat_history.append({"role": "assistant", "content": final_response})
                st.session_state["chat_history"] = chat_history

                # Log observability scores
                elapsed_ms = (time.time() - start_time) * 1000
                resolved = not result_state.get("requires_human", False)
                log_score(trace, "resolution_success", 1.0 if resolved else 0.0)
                log_score(trace, "response_time_ms", elapsed_ms)
                log_event(trace, "session_completed", {
                    "intent": result_state.get("intent"),
                    "ticket_id": current_ticket_id,
                    "requires_human": result_state.get("requires_human"),
                    "tool_calls": result_state.get("tool_calls_made", []),
                    "elapsed_ms": elapsed_ms,
                })

                # If the LLM detected the user wants to open a ticket, show the inline form
                if result_state.get("wants_ticket") and not current_ticket_id:
                    st.session_state["show_ticket_form"] = True

                # Rerun to refresh the layout: shows all messages via the
                # chat_history loop and re-renders st.chat_input cleanly.
                # (For escalation this also triggers the banner on next render.)
                st.rerun()

            except Exception as exc:
                logger.error("Graph execution failed: %s", exc)
                error_msg = (
                    "I'm experiencing technical difficulties. Your request has been logged "
                    "and a support specialist will contact you shortly."
                )
                st.markdown(error_msg)
                chat_history.append({"role": "assistant", "content": error_msg})
                st.session_state["chat_history"] = chat_history
                log_event(trace, "graph_error", {"error": str(exc)})
                st.rerun()




# ─── Main App ─────────────────────────────────────────────────────────────────

def main() -> None:
    _init_session_state()
    _inject_css()

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("🛒 Support Agent")
        st.divider()

        st.subheader("Customer Login")
        customer_id_input = st.text_input(
            "Customer ID",
            placeholder="e.g. CUST-001",
            value=st.session_state.get("_customer_id_input", ""),
        )

        col1, col2 = st.columns([3, 2])
        with col1:
            if st.button("Load Customer", use_container_width=True, type="primary"):
                if customer_id_input.strip():
                    st.session_state["_customer_id_input"] = customer_id_input.strip()
                    _resolve_current_ticket()
                    with st.spinner("Loading profile..."):
                        profile_result = get_customer_profile.invoke(
                            {"customer_id": customer_id_input.strip()}
                        )
                    if profile_result.get("success"):
                        st.session_state["customer_profile"] = profile_result
                        _reset_session()
                        st.success(f"Welcome, {profile_result['name']}!")
                    else:
                        st.error("Customer not found.")
        with col2:
            if st.button("New Chat", use_container_width=True):
                _resolve_current_ticket()
                _reset_session()
                st.rerun()

        # Customer profile display
        profile = st.session_state.get("customer_profile")
        if profile:
            st.divider()
            is_vip = profile.get("is_vip", False)
            tier_html = '<span class="vip-badge">⭐ VIP</span>' if is_vip else '<span class="std-badge">Standard</span>'
            st.markdown(
                f"""<div class="profile-card">
  <div class="profile-name">👤 {profile.get('name', 'N/A')}</div>
  <div class="profile-email">✉ {profile.get('email', 'N/A')}</div>
  <div>{tier_html}</div>
</div>
""",
                unsafe_allow_html=True,
            )
            fraud_score = profile.get("fraud_score", 0.0)
            if fraud_score > settings.fraud_score_threshold:
                st.warning(f"⚠️ Fraud Score: {fraud_score:.2f}")

        # Ticket history
        customer_id = st.session_state.get("_customer_id_input", "")
        if customer_id:
            st.divider()
            st.subheader("Ticket History")
            tickets = _get_ticket_history(customer_id)
            if tickets:
                for t in tickets:
                    with st.expander(f"{t['id']} — {_status_badge(t['status'])}"):
                        st.write(f"**Intent:** {t.get('intent', 'N/A')}")
                        st.write(f"**Priority:** {_priority_badge(t.get('priority', 'normal'))}")
                        st.write(f"**Created:** {t.get('created_at', 'N/A')[:10]}")
            else:
                st.info("No previous tickets.")

        # Download current chat
        _sidebar_history = st.session_state.get("chat_history", [])
        _sidebar_customer_id = st.session_state.get("_customer_id_input", "")
        if len(_sidebar_history) >= 2 and _sidebar_customer_id:
            st.divider()
            st.subheader("Download Current Chat")
            try:
                _pdf_data = chat_history_as_pdf(_sidebar_history, _sidebar_customer_id, settings.app_title)
            except Exception:
                _pdf_data = chat_history_as_txt(_sidebar_history, _sidebar_customer_id, settings.app_title)
            _txt_data = chat_history_as_txt(_sidebar_history, _sidebar_customer_id, settings.app_title)
            _dl_col1, _dl_col2 = st.columns(2)
            with _dl_col1:
                st.download_button(
                    label="⬇️ TXT",
                    data=_txt_data,
                    file_name=f"chat_{_sidebar_customer_id}.txt",
                    mime="text/plain",
                    use_container_width=True,
                    key="sidebar_dl_txt",
                )
            with _dl_col2:
                st.download_button(
                    label="⬇️ PDF",
                    data=_pdf_data,
                    file_name=f"chat_{_sidebar_customer_id}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="sidebar_dl_pdf",
                )

        # LangSmith trace URL for supervisors
        if st.session_state.get("trace_url"):
            st.divider()
            st.subheader("Observability")
            st.markdown(f"[🔍 View Trace]({st.session_state['trace_url']})")

    # ── Tabs ───────────────────────────────────────────────────────────────────
    tab_chat, tab_queue = st.tabs(["🤖 Customer Chat", "👤 Human Agent Queue"])

    with tab_chat:
        _render_customer_chat()

    with tab_queue:
        render_human_queue()

if __name__ == "__main__":
    main()
