"""Chat export utilities — TXT and PDF generation.

These functions are intentionally kept in a separate module so that Streamlit's
magic AST transformer (which only applies to the entry-point script) does not
wrap bare function-call statements with st.write(), which would render spurious
'None' values into the sidebar whenever the functions are called during rendering.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def chat_history_as_txt(chat_history: list[dict], customer_id: str, app_title: str) -> bytes:
    """Render chat history as plain UTF-8 text."""
    lines = [
        f"Chat Transcript — {app_title}",
        f"Customer: {customer_id}",
        f"Exported: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
        "",
    ]
    for msg in chat_history:
        role = "You" if msg["role"] == "user" else "Agent"
        lines += [f"[{role}]", str(msg["content"] or ""), ""]
    return "\n".join(lines).encode("utf-8")


def chat_history_as_pdf(chat_history: list[dict], customer_id: str, app_title: str) -> bytes:
    """Render chat history as a PDF using fpdf2."""
    from fpdf import FPDF
    import datetime

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(15, 52, 96)
    pdf.cell(0, 10, app_title, ln=True)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Customer: {customer_id}", ln=True)
    pdf.cell(
        0, 6,
        f"Exported: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ln=True,
    )
    pdf.ln(3)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    for msg in chat_history:
        is_user = msg["role"] == "user"

        pdf.set_font("Helvetica", "B", 9)
        if is_user:
            pdf.set_text_color(30, 30, 180)
        else:
            pdf.set_text_color(20, 120, 60)
        pdf.cell(0, 6, "You" if is_user else "Support Agent", ln=True)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 6, str(msg["content"] or ""))
        pdf.ln(3)

    return bytes(pdf.output())
