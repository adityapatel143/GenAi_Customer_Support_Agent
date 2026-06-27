"""Tests for tools — mock Supabase client to test each tool schema."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_supabase(monkeypatch):
    """Patch get_supabase_client to return a MagicMock."""
    mock_client = MagicMock()
    monkeypatch.setattr("src.database.supabase_client.get_supabase_client", lambda: mock_client)
    return mock_client


def _chain(mock_client, return_value):
    """Helper: configure a full Supabase query chain to return given data."""
    chain = MagicMock()
    chain.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.execute.return_value = MagicMock(data=return_value)
    mock_client.table.return_value = chain
    return chain


# ─── Order Tools ──────────────────────────────────────────────────────────────

class TestOrderTools:
    def test_get_order_status_success(self, monkeypatch):
        mock_client = MagicMock()
        order_data = {
            "id": "ORD-1042",
            "status": "shipped",
            "carrier": "USPS",
            "tracking_number": "USPS998877665",
            "estimated_delivery": "2026-05-01T00:00:00+00:00",
            "shipped_at": "2026-04-26T00:00:00+00:00",
            "ordered_at": "2026-04-24T00:00:00+00:00",
            "customer_id": "CUST-001",
        }
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[order_data])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.order_tools.get_supabase_client", lambda: mock_client)

        from src.tools.order_tools import get_order_status
        result = get_order_status.invoke({"order_id": "ORD-1042", "customer_id": "CUST-001"})

        assert result["success"] is True
        assert result["status"] == "shipped"
        assert result["carrier"] == "USPS"

    def test_get_order_status_not_found(self, monkeypatch):
        mock_client = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.order_tools.get_supabase_client", lambda: mock_client)

        from src.tools.order_tools import get_order_status
        result = get_order_status.invoke({"order_id": "ORD-9999", "customer_id": "CUST-001"})

        assert "error" in result

    def test_get_order_status_unauthorized(self, monkeypatch):
        """Order exists but belongs to a different customer — must be denied."""
        mock_client = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])  # .eq(customer_id) filters it out
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.order_tools.get_supabase_client", lambda: mock_client)

        from src.tools.order_tools import get_order_status
        result = get_order_status.invoke({"order_id": "ORD-1004", "customer_id": "CUST-001"})

        assert "error" in result
        assert result.get("unauthorized") is True

    def test_get_order_details_returns_full_record(self, monkeypatch):
        mock_client = MagicMock()
        order_data = {
            "id": "ORD-1001",
            "customer_id": "CUST-001",
            "status": "delivered",
            "items": [{"sku": "SHOE-42", "name": "Running Shoes", "qty": 1, "price": 89.99}],
            "total_amount": 89.99,
            "carrier": "FedEx",
            "tracking_number": "FX123456789",
        }
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[order_data])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.order_tools.get_supabase_client", lambda: mock_client)

        from src.tools.order_tools import get_order_details
        result = get_order_details.invoke({"order_id": "ORD-1001", "customer_id": "CUST-001"})

        assert result["success"] is True
        assert result["total_amount"] == 89.99
        assert isinstance(result["items"], list)

    def test_get_order_status_db_error(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.table.side_effect = Exception("DB connection error")
        monkeypatch.setattr("src.tools.order_tools.get_supabase_client", lambda: mock_client)

        from src.tools.order_tools import get_order_status
        result = get_order_status.invoke({"order_id": "ORD-1042", "customer_id": "CUST-001"})

        assert "error" in result

    def test_get_customer_orders_returns_list(self, monkeypatch):
        mock_client = MagicMock()
        orders = [
            {"id": "ORD-1042", "status": "shipped", "total_amount": 87.99,
             "items": [{"name": "Classic Sneakers", "qty": 1, "price": 75.00}],
             "ordered_at": "2026-04-24T00:00:00+00:00", "carrier": "USPS",
             "tracking_number": "USPS998877665", "estimated_delivery": "2026-05-01T00:00:00+00:00"},
            {"id": "ORD-1001", "status": "delivered", "total_amount": 89.99,
             "items": [{"name": "Running Shoes", "qty": 1, "price": 89.99}],
             "ordered_at": "2026-04-05T00:00:00+00:00", "carrier": "FedEx",
             "tracking_number": "FX123456789", "estimated_delivery": "2026-04-12T00:00:00+00:00"},
        ]
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = MagicMock(data=orders)
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.order_tools.get_supabase_client", lambda: mock_client)

        from src.tools.order_tools import get_customer_orders
        result = get_customer_orders.invoke({"customer_id": "CUST-001"})

        assert result["success"] is True
        assert result["count"] == 2
        assert isinstance(result["orders"], list)
        assert result["orders"][0]["id"] == "ORD-1042"

    def test_get_customer_orders_empty(self, monkeypatch):
        mock_client = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = MagicMock(data=[])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.order_tools.get_supabase_client", lambda: mock_client)

        from src.tools.order_tools import get_customer_orders
        result = get_customer_orders.invoke({"customer_id": "CUST-012"})

        assert result["success"] is True
        assert result["count"] == 0
        assert result["orders"] == []


# ─── Return Tools ─────────────────────────────────────────────────────────────

class TestReturnTools:
    def test_check_return_eligibility_delivered_within_window(self, monkeypatch):
        from datetime import datetime, timedelta, timezone
        mock_client = MagicMock()

        delivered = (datetime.now(tz=timezone.utc) - timedelta(days=5)).isoformat()
        order_data = {
            "id": "ORD-1001",
            "status": "delivered",
            "shipped_at": delivered,
            "estimated_delivery": delivered,
            "total_amount": 89.99,
            "customer_id": "CUST-001",
        }

        # First call: order query (with customer_id filter)
        order_chain = MagicMock()
        order_chain.select.return_value = order_chain
        order_chain.eq.return_value = order_chain
        order_chain.execute.return_value = MagicMock(data=[order_data])

        # Second call: existing returns query
        ret_chain = MagicMock()
        ret_chain.select.return_value = ret_chain
        ret_chain.eq.return_value = ret_chain
        ret_chain.execute.return_value = MagicMock(data=[])

        mock_client.table.side_effect = [order_chain, ret_chain]
        monkeypatch.setattr("src.tools.return_tools.get_supabase_client", lambda: mock_client)

        from src.tools.return_tools import check_return_eligibility
        result = check_return_eligibility.invoke({"order_id": "ORD-1001", "customer_id": "CUST-001"})

        assert result["eligible"] is True
        assert result["days_since_delivery"] == 5

    def test_check_return_eligibility_not_delivered(self, monkeypatch):
        mock_client = MagicMock()
        order_data = {
            "id": "ORD-1002",
            "status": "shipped",
            "estimated_delivery": None,
            "total_amount": 149.99,
            "customer_id": "CUST-002",
        }
        order_chain = MagicMock()
        order_chain.select.return_value = order_chain
        order_chain.eq.return_value = order_chain
        order_chain.execute.return_value = MagicMock(data=[order_data])
        mock_client.table.return_value = order_chain
        monkeypatch.setattr("src.tools.return_tools.get_supabase_client", lambda: mock_client)

        from src.tools.return_tools import check_return_eligibility
        result = check_return_eligibility.invoke({"order_id": "ORD-1002", "customer_id": "CUST-002"})

        assert result["eligible"] is False
        assert "shipped" in result["reason"]

    def test_check_return_eligibility_expired_window(self, monkeypatch):
        from datetime import datetime, timedelta, timezone
        mock_client = MagicMock()

        delivered = (datetime.now(tz=timezone.utc) - timedelta(days=45)).isoformat()
        order_data = {
            "id": "ORD-1004",
            "status": "delivered",
            "shipped_at": delivered,
            "estimated_delivery": delivered,
            "total_amount": 1299.99,
            "customer_id": "CUST-004",
        }
        order_chain = MagicMock()
        order_chain.select.return_value = order_chain
        order_chain.eq.return_value = order_chain
        order_chain.execute.return_value = MagicMock(data=[order_data])
        mock_client.table.return_value = order_chain
        monkeypatch.setattr("src.tools.return_tools.get_supabase_client", lambda: mock_client)

        from src.tools.return_tools import check_return_eligibility
        result = check_return_eligibility.invoke({"order_id": "ORD-1004", "customer_id": "CUST-004"})

        assert result["eligible"] is False
        assert "expired" in result["reason"]

    def test_check_return_eligibility_unauthorized(self, monkeypatch):
        """Order belongs to a different customer — must be denied."""
        mock_client = MagicMock()
        order_chain = MagicMock()
        order_chain.select.return_value = order_chain
        order_chain.eq.return_value = order_chain
        order_chain.execute.return_value = MagicMock(data=[])  # customer_id filter returns nothing
        mock_client.table.return_value = order_chain
        monkeypatch.setattr("src.tools.return_tools.get_supabase_client", lambda: mock_client)

        from src.tools.return_tools import check_return_eligibility
        result = check_return_eligibility.invoke({"order_id": "ORD-1004", "customer_id": "CUST-001"})

        assert result["eligible"] is False
        assert result.get("unauthorized") is True

    def test_create_rma_inserts_records(self, monkeypatch):
        mock_client = MagicMock()
        insert_chain = MagicMock()
        insert_chain.insert.return_value = insert_chain
        insert_chain.execute.return_value = MagicMock(data=[{"id": "RET-123"}])
        mock_client.table.return_value = insert_chain
        monkeypatch.setattr("src.tools.return_tools.get_supabase_client", lambda: mock_client)

        from src.tools.return_tools import create_rma
        result = create_rma.invoke({"order_id": "ORD-1001", "reason": "Damaged", "customer_id": "CUST-001"})

        assert result["success"] is True
        assert "rma_number" in result
        assert result["rma_number"].startswith("RMA-")
        assert "label_url" in result


# ─── Refund Tools ─────────────────────────────────────────────────────────────

class TestRefundTools:
    def test_check_refund_status_no_return(self, monkeypatch):
        mock_client = MagicMock()

        # return_requests query (filtered by customer_id) returns nothing
        ret_chain = MagicMock()
        ret_chain.select.return_value = ret_chain
        ret_chain.eq.return_value = ret_chain
        ret_chain.execute.return_value = MagicMock(data=[])

        # orders ownership check returns the order (valid customer)
        order_chain = MagicMock()
        order_chain.select.return_value = order_chain
        order_chain.eq.return_value = order_chain
        order_chain.execute.return_value = MagicMock(data=[{"id": "ORD-9999"}])

        mock_client.table.side_effect = [ret_chain, order_chain]
        monkeypatch.setattr("src.tools.refund_tools.get_supabase_client", lambda: mock_client)

        from src.tools.refund_tools import check_refund_status
        result = check_refund_status.invoke({"order_id": "ORD-9999", "customer_id": "CUST-001"})

        assert result["refund_found"] is False
        assert result.get("unauthorized") is not True

    def test_check_refund_status_unauthorized(self, monkeypatch):
        """Order belongs to a different customer — must be denied."""
        mock_client = MagicMock()

        ret_chain = MagicMock()
        ret_chain.select.return_value = ret_chain
        ret_chain.eq.return_value = ret_chain
        ret_chain.execute.return_value = MagicMock(data=[])

        # orders ownership check returns nothing (wrong customer)
        order_chain = MagicMock()
        order_chain.select.return_value = order_chain
        order_chain.eq.return_value = order_chain
        order_chain.execute.return_value = MagicMock(data=[])

        mock_client.table.side_effect = [ret_chain, order_chain]
        monkeypatch.setattr("src.tools.refund_tools.get_supabase_client", lambda: mock_client)

        from src.tools.refund_tools import check_refund_status
        result = check_refund_status.invoke({"order_id": "ORD-1004", "customer_id": "CUST-001"})

        assert result["refund_found"] is False
        assert result.get("unauthorized") is True

    def test_check_refund_status_refunded(self, monkeypatch):
        mock_client = MagicMock()

        ret_chain = MagicMock()
        ret_chain.select.return_value = ret_chain
        ret_chain.eq.return_value = ret_chain
        ret_chain.execute.return_value = MagicMock(data=[{
            "id": "RET-005", "status": "completed", "reason": "Arrived damaged",
            "requested_at": "2026-04-05T00:00:00+00:00", "approved_at": "2026-04-06T00:00:00+00:00",
        }])

        rma_chain = MagicMock()
        rma_chain.select.return_value = rma_chain
        rma_chain.eq.return_value = rma_chain
        rma_chain.execute.return_value = MagicMock(data=[{
            "id": "RMA-003",
            "rma_number": "RMA-20240103-003",
            "refund_amount": 399.99,
            "warehouse_received_at": "2026-04-10T00:00:00+00:00",
        }])

        mock_client.table.side_effect = [ret_chain, rma_chain]
        monkeypatch.setattr("src.tools.refund_tools.get_supabase_client", lambda: mock_client)

        from src.tools.refund_tools import check_refund_status
        result = check_refund_status.invoke({"order_id": "ORD-0998", "customer_id": "CUST-003"})

        assert result["refund_found"] is True
        assert result["refund_status"] == "refunded"
        assert result["refund_amount"] == 399.99

    def test_initiate_refund_updates_record(self, monkeypatch):
        mock_client = MagicMock()
        update_chain = MagicMock()
        update_chain.update.return_value = update_chain
        update_chain.eq.return_value = update_chain
        update_chain.execute.return_value = MagicMock(data=[{"id": "RMA-001"}])
        mock_client.table.return_value = update_chain
        monkeypatch.setattr("src.tools.refund_tools.get_supabase_client", lambda: mock_client)

        from src.tools.refund_tools import initiate_refund
        result = initiate_refund.invoke({"rma_id": "RMA-001", "amount": 89.99})

        assert result["success"] is True
        assert result["refund_amount"] == 89.99
        assert "3-5 business days" in result["estimated_days"]


# ─── Customer Tools ────────────────────────────────────────────────────────────

class TestCustomerTools:
    def test_get_customer_profile_success(self, monkeypatch):
        mock_client = MagicMock()
        customer_data = {
            "id": "CUST-001",
            "email": "alice@example.com",
            "name": "Alice Johnson",
            "is_vip": True,
            "fraud_score": 0.0,
            "created_at": "2025-04-30T00:00:00+00:00",
        }
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=customer_data)
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.customer_tools.get_supabase_client", lambda: mock_client)

        from src.tools.customer_tools import get_customer_profile
        result = get_customer_profile.invoke({"customer_id": "CUST-001"})

        assert result["success"] is True
        assert result["name"] == "Alice Johnson"
        assert result["is_vip"] is True

    def test_flag_fraud_risk_updates_score(self, monkeypatch):
        mock_client = MagicMock()
        chain = MagicMock()
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": "CUST-004"}])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.customer_tools.get_supabase_client", lambda: mock_client)

        from src.tools.customer_tools import flag_fraud_risk
        result = flag_fraud_risk.invoke({"customer_id": "CUST-004", "reason": "Multiple suspicious returns"})

        assert result["success"] is True
        assert result["fraud_score"] == 0.9


# ─── Ticket Tools ─────────────────────────────────────────────────────────────

class TestTicketTools:
    def test_create_ticket_returns_id(self, monkeypatch):
        mock_client = MagicMock()
        chain = MagicMock()
        chain.insert.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": "TKT-ABCD1234"}])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.ticket_tools.get_supabase_client", lambda: mock_client)

        from src.tools.ticket_tools import create_ticket
        result = create_ticket.invoke({
            "customer_id": "CUST-001",
            "order_id": "ORD-1042",
            "intent": "wismo",
            "priority": "normal",
        })

        assert result["success"] is True
        assert result["ticket_id"].startswith("TKT-")

    def test_escalate_ticket_updates_status(self, monkeypatch):
        mock_client = MagicMock()
        chain = MagicMock()
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": "TKT-001"}])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.ticket_tools.get_supabase_client", lambda: mock_client)

        from src.tools.ticket_tools import escalate_ticket
        result = escalate_ticket.invoke({
            "ticket_id": "TKT-001",
            "reason": "Customer demanded manager",
            "priority": "urgent",
        })

        assert result["success"] is True
        assert result["status"] == "escalated"
        assert result["priority"] == "urgent"

    def test_get_ticket_returns_status(self, monkeypatch):
        mock_client = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{
            "id": "TKT-001",
            "customer_id": "CUST-001",
            "order_id": "ORD-1042",
            "intent": "wismo",
            "status": "in_progress",
            "priority": "normal",
            "created_at": "2026-04-30T10:00:00Z",
            "updated_at": "2026-04-30T10:05:00Z",
        }])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.ticket_tools.get_supabase_client", lambda: mock_client)

        from src.tools.ticket_tools import get_ticket
        result = get_ticket.invoke({"ticket_id": "TKT-001", "customer_id": "CUST-001"})

        assert result["success"] is True
        assert result["ticket_id"] == "TKT-001"
        assert result["status"] == "in_progress"
        assert result["priority"] == "normal"
        assert result["intent"] == "wismo"

    def test_get_ticket_not_found(self, monkeypatch):
        mock_client = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])
        mock_client.table.return_value = chain
        monkeypatch.setattr("src.tools.ticket_tools.get_supabase_client", lambda: mock_client)

        from src.tools.ticket_tools import get_ticket
        result = get_ticket.invoke({"ticket_id": "TKT-999", "customer_id": "CUST-002"})

        assert result["success"] is False
        assert "not found" in result["error"]
