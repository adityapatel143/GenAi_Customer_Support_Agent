"""Human Agent Queue Dashboard — renders inside the Human Agent Queue tab."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from src.config import get_settings
from src.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── Database helpers ─────────────────────────────────────────────────────────

def _fetch_queue(statuses: list[str], priority: str | None) -> list[dict[str, Any]]:
    db = get_supabase_client()
    query = (
        db.table("tickets")
        .select("id, customer_id, order_id, intent, status, priority, created_at, updated_at, resolved_by, conversation")
        .in_("status", statuses)
        .order("created_at", desc=False)  # oldest first in queue
    )
    if priority:
        query = query.eq("priority", priority)
    return query.limit(200).execute().data or []


def _fetch_customer(customer_id: str) -> dict[str, Any]:
    db = get_supabase_client()
    result = db.table("customers").select("*").eq("id", customer_id).execute()
    return result.data[0] if result.data else {}


def _fetch_order(order_id: str, customer_id: str | None = None) -> dict[str, Any]:
    db = get_supabase_client()
    query = db.table("orders").select("*").eq("id", order_id)
    if customer_id:
        query = query.eq("customer_id", customer_id)
    result = query.execute()
    return result.data[0] if result.data else {}


def _fetch_return_requests(order_id: str) -> list[dict[str, Any]]:
    db = get_supabase_client()
    return db.table("return_requests").select("*").eq("order_id", order_id).execute().data or []


def _fetch_rma_records(return_request_id: str) -> list[dict[str, Any]]:
    db = get_supabase_client()
    return db.table("rma_records").select("*").eq("return_request_id", return_request_id).execute().data or []


def _update_ticket_status(ticket_id: str, status: str, resolved_by: str | None = None) -> bool:
    try:
        db = get_supabase_client()
        payload: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        if resolved_by:
            payload["resolved_by"] = resolved_by
        db.table("tickets").update(payload).eq("id", ticket_id).execute()
        return True
    except Exception as exc:
        logger.error("Failed to update ticket %s status: %s", ticket_id, exc)
        return False


def _update_ticket_priority(ticket_id: str, priority: str) -> bool:
    try:
        db = get_supabase_client()
        db.table("tickets").update({
            "priority": priority,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }).eq("id", ticket_id).execute()
        return True
    except Exception as exc:
        logger.error("Failed to update ticket %s priority: %s", ticket_id, exc)
        return False


def _add_agent_note(ticket_id: str, note: str) -> bool:
    """Append a human agent note to the ticket's conversation in the database.

    Always re-fetches the current conversation from the DB before appending to avoid
    overwriting messages added by the AI or another agent since the queue was loaded.
    """
    try:
        db = get_supabase_client()
        # Re-fetch the current conversation to avoid overwriting concurrent updates
        result = db.table("tickets").select("conversation").eq("id", ticket_id).execute()
        current_conv: list[dict] = (result.data[0].get("conversation") or []) if result.data else []
        updated_conv = current_conv + [{
            "role": "human_agent",
            "content": note,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }]
        db.table("tickets").update({
            "conversation": updated_conv,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }).eq("id", ticket_id).execute()
        return True
    except Exception as exc:
        logger.error("Failed to add note to ticket %s: %s", ticket_id, exc)
        return False


def _process_refund(rma_id: str, amount: float) -> dict[str, Any]:
    try:
        from src.tools.refund_tools import initiate_refund
        return initiate_refund.invoke({"rma_id": rma_id, "amount": amount})
    except Exception as exc:
        logger.error("initiate_refund failed for %s: %s", rma_id, exc)
        return {"success": False, "error": str(exc)}


def _update_return_status(return_id: str, status: str) -> bool:
    try:
        db = get_supabase_client()
        now = datetime.now(tz=timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "status": status,
            "updated_at": now,
        }
        if status == "approved":
            payload["approved_at"] = now
        db.table("return_requests").update(payload).eq("id", return_id).execute()
        return True
    except Exception as exc:
        logger.error("Failed to update return %s: %s", return_id, exc)
        return False


# ─── Badge helpers ────────────────────────────────────────────────────────────

def _status_icon(status: str) -> str:
    return {"open": "🟡", "in_progress": "🔵", "escalated": "🔴", "resolved": "🟢", "closed": "⚫"}.get(status, "⚪")


def _priority_icon(priority: str) -> str:
    return {"low": "🟢", "normal": "🔵", "high": "🟠", "urgent": "🔴"}.get(priority, "⚪")


_STATUS_COLOR = {
    "open": ("#744210", "#fefcbf", "#f6e05e"),
    "in_progress": ("#1a365d", "#ebf8ff", "#90cdf4"),
    "escalated": ("#742a2a", "#fff5f5", "#fc8181"),
    "resolved": ("#1c4532", "#f0fff4", "#68d391"),
    "closed": ("#1a202c", "#edf2f7", "#a0aec0"),
}
_PRIORITY_COLOR = {
    "low": ("#1c4532", "#f0fff4", "#68d391"),
    "normal": ("#1a365d", "#ebf8ff", "#90cdf4"),
    "high": ("#7b341e", "#fffaf0", "#f6ad55"),
    "urgent": ("#742a2a", "#fff5f5", "#fc8181"),
}


def _badge(label: str, colors: tuple) -> str:
    fg, bg, border = colors
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'border:1px solid {border};border-radius:20px;padding:2px 10px;'
        f'font-size:0.73rem;font-weight:700;letter-spacing:0.3px;margin:0 3px">'
        f'{label}</span>'
    )


def _status_badge(status: str) -> str:
    icon = _status_icon(status)
    return _badge(f"{icon} {status.upper()}", _STATUS_COLOR.get(status, ("#1a202c", "#edf2f7", "#a0aec0")))


def _priority_badge(priority: str) -> str:
    icon = _priority_icon(priority)
    return _badge(f"{icon} {priority.upper()}", _PRIORITY_COLOR.get(priority, ("#1a365d", "#ebf8ff", "#90cdf4")))


def _inject_queue_css() -> None:
    st.markdown("""
<style>
/* ── Queue hero ───────────────────────────────────────────────────────── */
.queue-hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 18px;
    padding: 1.6rem 2.2rem;
    color: #fff;
    margin-bottom: 1.4rem;
    box-shadow: 0 8px 32px rgba(15,52,96,0.35);
    position: relative;
    overflow: hidden;
}
.queue-hero::after {
    content: '';
    position: absolute;
    top: -50px; right: -30px;
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(102,126,234,0.3) 0%, transparent 70%);
    pointer-events: none;
}
.queue-hero h2 { margin: 0 0 0.25rem; font-size: 1.65rem; font-weight: 800; letter-spacing: -0.4px; }
.queue-hero p  { margin: 0; opacity: 0.72; font-size: 0.9rem; }

/* ── Stat cards ───────────────────────────────────────────────────────── */
.stat-row { display: flex; gap: 12px; margin-bottom: 1.2rem; }
.stat-card {
    flex: 1;
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 1rem 1.2rem;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}
.stat-card .stat-num { font-size: 2rem; font-weight: 800; line-height: 1.1; }
.stat-card .stat-lbl { font-size: 0.75rem; color: #718096; margin-top: 4px; }
.stat-card.red  .stat-num { color: #c53030; }
.stat-card.blue .stat-num { color: #2b6cb0; }
.stat-card.gold .stat-num { color: #b7791f; }
.stat-card.purp .stat-num { color: #6b46c1; }

/* ── Ticket card ──────────────────────────────────────────────────────── */
.tkt-card {
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 1rem 1.3rem;
    margin-bottom: 0.6rem;
    background: #fff;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    display: flex;
    align-items: center;
    gap: 14px;
    cursor: pointer;
}
.tkt-card.urgent  { border-left: 4px solid #fc8181; }
.tkt-card.escalated { border-left: 4px solid #f6ad55; }
.tkt-card.in_progress { border-left: 4px solid #90cdf4; }
.tkt-card.open    { border-left: 4px solid #f6e05e; }
.tkt-id { font-family: monospace; font-size: 0.85rem; color: #4a5568; font-weight: 700; white-space: nowrap; }
.tkt-name { font-weight: 700; font-size: 0.95rem; color: #1a202c; }
.tkt-meta { font-size: 0.78rem; color: #718096; margin-top: 2px; }

/* ── Info cards ───────────────────────────────────────────────────────── */
.info-card {
    background: linear-gradient(135deg, #ebf4ff 0%, #e8f0fe 100%);
    border: 1px solid #c3d8f5;
    border-radius: 14px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.8rem;
}
.info-card h4 { margin: 0 0 0.5rem; font-size: 0.95rem; color: #2b6cb0; font-weight: 700; }
.info-card .info-row { font-size: 0.85rem; color: #2d3748; margin: 3px 0; }
.info-card .info-row strong { color: #1a202c; }

/* ── Conversation ─────────────────────────────────────────────────────── */
.conv-wrap {
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1rem;
    margin-bottom: 1rem;
    max-height: 320px;
    overflow-y: auto;
}
</style>
""", unsafe_allow_html=True)


def _render_stats() -> None:
    try:
        db = get_supabase_client()
        all_tickets = db.table("tickets").select("status, priority").execute().data or []

        escalated   = sum(1 for t in all_tickets if t["status"] == "escalated")
        in_progress = sum(1 for t in all_tickets if t["status"] == "in_progress")
        open_count  = sum(1 for t in all_tickets if t["status"] == "open")
        urgent      = sum(1 for t in all_tickets if t["priority"] == "urgent" and t["status"] not in ("resolved", "closed"))

        st.markdown(
            f"""
<div class="stat-row">
  <div class="stat-card red"><div class="stat-num">{escalated}</div><div class="stat-lbl">🔴 Escalated</div></div>
  <div class="stat-card blue"><div class="stat-num">{in_progress}</div><div class="stat-lbl">🔵 In Progress</div></div>
  <div class="stat-card gold"><div class="stat-num">{open_count}</div><div class="stat-lbl">🟡 Open</div></div>
  <div class="stat-card purp"><div class="stat-num">{urgent}</div><div class="stat-lbl">🚨 Urgent Active</div></div>
</div>
""",
            unsafe_allow_html=True,
        )
    except Exception as exc:
        st.warning(f"Could not load stats: {exc}")


# ─── Ticket detail ────────────────────────────────────────────────────────────

def _render_ticket_detail(ticket: dict[str, Any]) -> None:
    ticket_id   = ticket["id"]
    customer_id = ticket["customer_id"]
    order_id    = ticket.get("order_id")
    conversation: list[dict] = ticket.get("conversation") or []

    customer = _fetch_customer(customer_id)
    order    = _fetch_order(order_id, customer_id) if order_id else {}

    # Fetch return requests once — reused by both Act 2 (refunds) and Act 3 (returns)
    returns = _fetch_return_requests(order_id) if order_id else []

    # ── Customer + Order info ──────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        name        = customer.get("name", customer_id)
        is_vip      = customer.get("is_vip", False)
        fraud_score = customer.get("fraud_score", 0.0)
        vip_html    = ' &nbsp;<span style="background:linear-gradient(135deg,#f6d365,#fda085);color:#744210;border-radius:20px;padding:2px 8px;font-size:0.7rem;font-weight:700">⭐ VIP</span>' if is_vip else ""
        fraud_html  = f'<div class="info-row" style="color:#c53030;font-weight:700">⚠️ High Fraud Score: {fraud_score:.2f}</div>' if fraud_score > settings.fraud_score_threshold else f'<div class="info-row"><strong>Fraud Score:</strong> {fraud_score:.2f}</div>'

        items_html = ""
        if order:
            for item in (order.get("items") or []):
                items_html += f"<div class='info-row'>  &bull; {item.get('name', item.get('sku', '?'))} &times; {item.get('qty', 1)} &mdash; ${item.get('price', 0):.2f}</div>"
            tracking_html = f"<div class='info-row'><strong>Tracking:</strong> <code>{order['tracking_number']}</code> via {order.get('carrier','?')}</div>" if order.get("tracking_number") else ""
            order_html = f"""
<div class="info-card" style="margin-top:0.6rem">
  <h4>📦 Order</h4>
  <div class='info-row'><strong>Order ID:</strong> <code>{order_id}</code></div>
  <div class='info-row'><strong>Status:</strong> {order.get('status','N/A').upper()}</div>
  <div class='info-row'><strong>Total:</strong> ${order.get('total_amount',0):.2f}</div>
  {items_html}{tracking_html}
</div>"""
        else:
            order_html = ""

        st.markdown(
            f"""
<div class="info-card">
  <h4>👤 Customer</h4>
  <div class='info-row'><strong>Name:</strong> {name}{vip_html}</div>
  <div class='info-row'><strong>Email:</strong> {customer.get('email','N/A')}</div>
  <div class='info-row'><strong>ID:</strong> <code>{customer_id}</code></div>
  {fraud_html}
</div>
{order_html}
""",
            unsafe_allow_html=True,
        )

    with col_right:
        created = ticket.get("created_at", "")[:16].replace("T", " ")
        updated = ticket.get("updated_at", "")[:16].replace("T", " ")
        resolved_html = f"<div class='info-row'><strong>Resolved by:</strong> <code>{ticket['resolved_by']}</code></div>" if ticket.get("resolved_by") else ""
        st.markdown(
            f"""
<div class="info-card">
  <h4>🎫 Ticket</h4>
  <div class='info-row'><strong>Ticket ID:</strong> <code>{ticket_id}</code></div>
  <div class='info-row'><strong>Intent:</strong> <code>{ticket.get('intent','N/A')}</code></div>
  <div class='info-row'><strong>Status:</strong> {_status_badge(ticket['status'])}</div>
  <div class='info-row'><strong>Priority:</strong> {_priority_badge(ticket['priority'])}</div>
  <div class='info-row'><strong>Created:</strong> {created}</div>
  <div class='info-row'><strong>Updated:</strong> {updated}</div>
  {resolved_html}
</div>
""",
            unsafe_allow_html=True,
        )

    # ── Conversation history ───────────────────────────────────────────────────
    if conversation:
        st.subheader("💬 Conversation")
        for msg in conversation:
            role    = msg.get("role", "unknown")
            content = msg.get("content", "")
            ts      = msg.get("timestamp", "")[:16].replace("T", " ") if msg.get("timestamp") else ""

            if role in ("user", "customer"):
                with st.chat_message("user"):
                    st.write(content)
                    if ts:
                        st.caption(ts)
            elif role in ("agent", "assistant"):
                with st.chat_message("assistant"):
                    st.write(content)
                    if ts:
                        st.caption(ts)
            elif role == "human_agent":
                with st.chat_message("assistant", avatar="👤"):
                    st.info(f"🧑‍💼 **Human Agent:** {content}")
                    if ts:
                        st.caption(ts)

    st.divider()

    # ── Action tabs ───────────────────────────────────────────────────────────
    st.subheader("⚡ Actions")
    act1, act2, act3, act4, act5 = st.tabs(
        ["📋 Status & Priority", "💰 Refund Processing", "📦 Return Requests", "🎁 Store Credit", "📝 Agent Notes"]
    )

    # ── Act 1: Status & Priority ───────────────────────────────────────────────
    with act1:
        col_s, col_p = st.columns(2)

        status_options   = ["open", "in_progress", "escalated", "resolved", "closed"]
        priority_options = ["low", "normal", "high", "urgent"]

        with col_s:
            st.write("**Update Status**")
            cur_status_idx = status_options.index(ticket["status"]) if ticket["status"] in status_options else 0
            new_status = st.selectbox(
                "New status",
                status_options,
                index=cur_status_idx,
                key=f"sel_status_{ticket_id}",
                label_visibility="collapsed",
            )
            resolved_by = "human" if new_status in ("resolved", "closed") else None
            if st.button("✅ Apply Status", key=f"btn_status_{ticket_id}", use_container_width=True, type="primary"):
                if _update_ticket_status(ticket_id, new_status, resolved_by):
                    st.success(f"Status → **{new_status}**")
                    st.rerun()
                else:
                    st.error("Failed to update status.")

        with col_p:
            st.write("**Update Priority**")
            cur_prio_idx = priority_options.index(ticket["priority"]) if ticket["priority"] in priority_options else 1
            new_priority = st.selectbox(
                "New priority",
                priority_options,
                index=cur_prio_idx,
                key=f"sel_prio_{ticket_id}",
                label_visibility="collapsed",
            )
            if st.button("🔺 Apply Priority", key=f"btn_prio_{ticket_id}", use_container_width=True):
                if _update_ticket_priority(ticket_id, new_priority):
                    st.success(f"Priority → **{new_priority}**")
                    st.rerun()
                else:
                    st.error("Failed to update priority.")

    # ── Act 2: Refund Processing ───────────────────────────────────────────────
    with act2:
        if not order_id:
            st.info("No order linked to this ticket.")
        else:
            if not returns:
                st.info("No return requests found for this order.")
            else:
                for ret in returns:
                    rmas = _fetch_rma_records(ret["id"])
                    with st.expander(
                        f"Return `{ret['id']}` — {ret.get('reason', '')} — Status: **{ret['status'].upper()}**",
                        expanded=True,
                    ):
                        if not rmas:
                            st.warning("No RMA record exists for this return request yet.")
                        else:
                            for rma in rmas:
                                rma_id          = rma["id"]
                                existing_refund = rma.get("refund_amount")
                                warehouse_rcvd  = rma.get("warehouse_received_at")
                                order_amount    = order.get("total_amount", 0.0)

                                st.write(f"**RMA Number:** `{rma.get('rma_number', rma_id)}`")
                                if warehouse_rcvd:
                                    st.success(f"✅ Warehouse received: {str(warehouse_rcvd)[:10]}")
                                else:
                                    st.warning("⚠️ Item not yet received at warehouse.")

                                if existing_refund is not None:
                                    st.success(f"✅ Refund already processed: **${existing_refund:.2f}**")
                                else:
                                    if not warehouse_rcvd:
                                        st.caption("Human agents can override and process the refund before warehouse receipt.")
                                    refund_input = st.number_input(
                                        "Refund Amount ($)",
                                        min_value=0.01,
                                        max_value=float(order_amount) * 1.1,
                                        value=float(order_amount),
                                        step=0.01,
                                        key=f"refund_amt_{rma_id}",
                                    )
                                    if st.button(
                                        f"💰 Process Refund ${refund_input:.2f}",
                                        key=f"btn_refund_{rma_id}",
                                        use_container_width=True,
                                        type="primary",
                                    ):
                                        result = _process_refund(rma_id, refund_input)
                                        if result.get("success"):
                                            st.success(f"✅ Refund of **${refund_input:.2f}** processed!")
                                            _update_ticket_status(ticket_id, "resolved", "human")
                                            st.rerun()
                                        else:
                                            st.error(f"Refund failed: {result.get('error', 'Unknown error')}")

    # ── Act 3: Return Requests ─────────────────────────────────────────────────
    with act3:
        if not order_id:
            st.info("No order linked to this ticket.")
        else:
            if not returns:
                st.info("No return requests found for this order.")
            else:
                for ret in returns:
                    with st.expander(
                        f"Return `{ret['id']}` — {ret.get('reason', '')} — **{ret['status'].upper()}**",
                        expanded=True,
                    ):
                        st.write(f"**Reason:** {ret.get('reason', 'N/A')}")
                        st.write(f"**Requested:** {ret.get('requested_at', '')[:10]}")
                        if ret.get("approved_at"):
                            st.write(f"**Approved at:** {ret['approved_at'][:10]}")
                        st.write(f"**Current Status:** `{ret['status'].upper()}`")

                        if ret["status"] in ("pending", "rejected"):
                            col_a, col_r = st.columns(2)
                            with col_a:
                                if st.button(
                                    "✅ Approve Return",
                                    key=f"btn_approve_{ret['id']}_{ticket_id}",
                                    use_container_width=True,
                                    type="primary",
                                ):
                                    if _update_return_status(ret["id"], "approved"):
                                        st.success("Return approved!")
                                        st.rerun()
                                    else:
                                        st.error("Failed to approve return.")
                            with col_r:
                                if st.button(
                                    "❌ Reject Return",
                                    key=f"btn_reject_{ret['id']}_{ticket_id}",
                                    use_container_width=True,
                                ):
                                    if _update_return_status(ret["id"], "rejected"):
                                        st.warning("Return rejected.")
                                        st.rerun()
                                    else:
                                        st.error("Failed to reject return.")
                        elif ret["status"] == "approved":
                            if st.button(
                                "✅ Mark Completed",
                                key=f"btn_complete_{ret['id']}_{ticket_id}",
                                use_container_width=True,
                            ):
                                if _update_return_status(ret["id"], "completed"):
                                    st.success("Return marked as completed.")
                                    st.rerun()
                                else:
                                    st.error("Failed to update return.")

    # ── Act 4: Store Credit ────────────────────────────────────────────────────
    with act4:
        from src.tools.credit_tools import apply_store_credit, get_store_credits

        # Cache credits per customer to avoid a LangSmith-traced DB call on every render.
        _cache_key = f"_store_credits_{customer_id}"
        if _cache_key not in st.session_state:
            try:
                st.session_state[_cache_key] = get_store_credits.invoke({"customer_id": customer_id})
            except Exception as exc:
                st.session_state[_cache_key] = {"credits": [], "total_active_amount": 0, "_error": str(exc)}

        credit_data = st.session_state[_cache_key]
        if credit_data.get("_error"):
            st.warning(f"Could not load store credits: {credit_data['_error']}")
        else:
            active_credits = [c for c in (credit_data.get("credits") or []) if c.get("status") == "active"]
            if active_credits:
                st.write(f"**Active credits on account:** ${credit_data.get('total_active_amount', 0):.2f}")
                for c in active_credits:
                    st.write(
                        f"  • `{c['id']}` — **${c['amount']:.2f}** | "
                        f"{c.get('reason', '')} | expires {c.get('expires_at', '')[:10]}"
                    )
                st.divider()
            else:
                st.info("No active store credits on this account.")

        st.write("**Issue a new store credit**")
        credit_amount = st.number_input(
            "Credit Amount ($)",
            min_value=1.0,
            max_value=500.0,
            value=10.0,
            step=1.0,
            key=f"credit_amt_{ticket_id}",
        )
        credit_reason = st.text_input(
            "Reason",
            value="Goodwill credit — escalation",
            key=f"credit_reason_{ticket_id}",
        )
        if st.button("🎁 Apply Store Credit", key=f"btn_credit_{ticket_id}", use_container_width=True, type="primary"):
            if credit_reason.strip():
                try:
                    result = apply_store_credit.invoke({
                        "customer_id": customer_id,
                        "amount": credit_amount,
                        "reason": credit_reason.strip(),
                        "issued_by": "human",
                    })
                    if result.get("success"):
                        st.success(f"✅ Store credit of **${credit_amount:.2f}** applied! Reference: `{result['credit_id']}`")
                        # Bust the cache so the updated credits list is fetched on next render
                        st.session_state.pop(f"_store_credits_{customer_id}", None)
                        st.rerun()
                    else:
                        st.error(f"Failed: {result.get('error', 'Unknown error')}")
                except Exception as exc:
                    st.error(f"Error applying credit: {exc}")
            else:
                st.warning("Please provide a reason for the credit.")

    # ── Act 5: Agent Notes ─────────────────────────────────────────────────────
    with act5:
        st.write("Notes are appended to the ticket's conversation history and timestamped.")
        note_text = st.text_area(
            "Agent Note",
            placeholder="e.g. Spoke with customer, processing full refund as goodwill gesture due to delayed delivery...",
            key=f"note_text_{ticket_id}",
            height=120,
        )
        if st.button("💾 Save Note", key=f"btn_note_{ticket_id}", use_container_width=True):
            if note_text.strip():
                if _add_agent_note(ticket_id, note_text.strip()):
                    st.success("Note saved to ticket.")
                    st.rerun()
                else:
                    st.error("Failed to save note.")
            else:
                st.warning("Note cannot be empty.")


# ─── Main render ──────────────────────────────────────────────────────────────

def render_human_queue() -> None:
    """Render the full human agent queue dashboard."""
    _inject_queue_css()

    st.markdown(
        """
<div class="queue-hero">
  <h2>👤 Human Agent Queue</h2>
  <p>Review escalated tickets &nbsp;&middot;&nbsp; Process refunds &nbsp;&middot;&nbsp; Approve returns &nbsp;&middot;&nbsp; Issue store credits</p>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── Stats ─────────────────────────────────────────────────────────────────
    _render_stats()
    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.container():
        col_f1, col_f2, col_f3 = st.columns([3, 2, 1])
        with col_f1:
            status_filter = st.multiselect(
                "Status",
                ["open", "in_progress", "escalated"],
                default=["escalated", "in_progress"],
                key="hq_status_filter",
            )
        with col_f2:
            priority_raw = st.selectbox(
                "Priority",
                ["All", "urgent", "high", "normal", "low"],
                index=0,
                key="hq_priority_filter",
            )
        with col_f3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("🔄 Refresh", use_container_width=True):
                st.rerun()

    if not status_filter:
        st.info("Select at least one status filter above to show tickets.")
        return

    priority_filter = None if priority_raw == "All" else priority_raw

    # ── Load queue ────────────────────────────────────────────────────────────
    try:
        tickets = _fetch_queue(status_filter, priority_filter)
    except Exception as exc:
        st.error(f"Could not load queue: {exc}")
        return

    if not tickets:
        st.success("✅ Queue is empty — no tickets match the selected filters.")
        return

    # Sort: urgent first, then escalated, then by creation time
    _prio_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    _stat_order = {"escalated": 0, "in_progress": 1, "open": 2}
    tickets.sort(key=lambda t: (
        _prio_order.get(t["priority"], 9),
        _stat_order.get(t["status"], 9),
        t.get("created_at", ""),
    ))

    st.caption(f"{len(tickets)} ticket(s) in queue")

    # Batch-fetch all unique customers in one query to avoid N+1 DB calls
    unique_customer_ids = list({t["customer_id"] for t in tickets})
    try:
        db = get_supabase_client()
        cust_rows = (
            db.table("customers")
            .select("id, name, is_vip, fraud_score")
            .in_("id", unique_customer_ids)
            .execute()
            .data or []
        )
        customers_map: dict[str, dict] = {c["id"]: c for c in cust_rows}
    except Exception:
        customers_map = {}

    # ── Ticket rows ───────────────────────────────────────────────────────────
    for ticket in tickets:
        ticket_id   = ticket["id"]
        customer_id = ticket["customer_id"]

        cust        = customers_map.get(customer_id, {})
        name        = cust.get("name", customer_id)
        is_vip      = cust.get("is_vip", False)
        fraud_score = cust.get("fraud_score", 0.0)

        intent  = ticket.get("intent", "N/A")
        created = ticket.get("created_at", "")[:10]

        extra_badges = []
        if is_vip:
            extra_badges.append('<span style="background:linear-gradient(135deg,#f6d365,#fda085);color:#744210;border-radius:20px;padding:2px 8px;font-size:0.7rem;font-weight:700">⭐ VIP</span>')
        if fraud_score > settings.fraud_score_threshold:
            extra_badges.append('<span style="background:#fff5f5;color:#c53030;border:1px solid #fc8181;border-radius:20px;padding:2px 8px;font-size:0.7rem;font-weight:700">⚠️ FRAUD</span>')
        extra_html = " ".join(extra_badges)

        card_class = "urgent" if ticket["priority"] == "urgent" else ticket["status"]
        header_html = (
            f'<div class="tkt-card {card_class}">'
            f'<div><div class="tkt-id">{ticket_id}</div></div>'
            f'<div style="flex:1">'
            f'<div class="tkt-name">{name} {extra_html}</div>'
            f'<div class="tkt-meta">{_status_badge(ticket["status"])} {_priority_badge(ticket["priority"])} &nbsp; Intent: <code>{intent}</code> &nbsp; {created}</div>'
            f'</div></div>'
        )

        # Auto-expand escalated / urgent tickets
        auto_expand = ticket["status"] == "escalated" or ticket["priority"] == "urgent"
        with st.expander(f"{ticket_id}  ·  {name}  ·  {ticket['status'].upper()}  ·  {ticket['priority'].upper()}", expanded=auto_expand):
            st.markdown(header_html, unsafe_allow_html=True)
            _render_ticket_detail(ticket)
