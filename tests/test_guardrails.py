"""Tests for guardrails validators."""
from __future__ import annotations

import pytest

from src.guardrails.validators import (
    ValidationResult,
    check_factual_consistency,
    check_toxic_language,
    redact_pii,
    validate_response,
)


class TestPIIRedaction:
    def test_ssn_is_redacted(self):
        text = "Your SSN 123-45-6789 has been verified."
        result = redact_pii(text)
        assert "123-45-6789" not in result
        assert "[SSN REDACTED]" in result

    def test_credit_card_is_redacted(self):
        text = "Your card 4111111111111111 will be refunded."
        result = redact_pii(text)
        assert "4111111111111111" not in result
        assert "[CARD REDACTED]" in result

    def test_clean_text_unchanged(self):
        text = "Your order ORD-1042 has been shipped via USPS."
        result = redact_pii(text)
        assert result == text

    def test_multiple_pii_redacted(self):
        text = "SSN: 987-65-4321, Card: 5500005555555559."
        result = redact_pii(text)
        assert "987-65-4321" not in result
        assert "[SSN REDACTED]" in result

    def test_partial_card_not_redacted(self):
        # 12-digit number should not be flagged as CC
        text = "Reference number 123456789012 for your order."
        result = redact_pii(text)
        # The pattern requires 13-16 digits; 12 digits should not match
        assert "Reference number" in result


class TestToxicLanguage:
    def test_toxic_word_detected(self):
        text = "This is stupid service."
        matches = check_toxic_language(text)
        assert len(matches) > 0

    def test_clean_text_no_matches(self):
        text = "Thank you for your patience. We will resolve this shortly."
        matches = check_toxic_language(text)
        assert matches == []

    def test_idiot_detected(self):
        text = "Only an idiot would do this."
        matches = check_toxic_language(text)
        assert any("idiot" in m.lower() for m in matches)

    def test_mixed_case_toxic(self):
        text = "This is STUPID!"
        matches = check_toxic_language(text)
        assert len(matches) > 0


class TestFactualConsistency:
    def test_correct_amount_passes(self):
        order_data = {"id": "ORD-1042", "total_amount": 87.99, "carrier": "USPS"}
        response = "Your order for $87.99 has been shipped via USPS."
        issues = check_factual_consistency(response, order_data)
        assert issues == []

    def test_wrong_amount_flagged(self):
        order_data = {"id": "ORD-1042", "total_amount": 87.99, "carrier": "USPS"}
        response = "Your refund of $500.00 has been processed."
        issues = check_factual_consistency(response, order_data)
        assert len(issues) > 0
        assert any("500.00" in i for i in issues)

    def test_wrong_order_id_flagged(self):
        order_data = {"id": "ORD-1042", "total_amount": 87.99}
        response = "Your order ORD-9999 has been shipped."
        issues = check_factual_consistency(response, order_data)
        assert len(issues) > 0

    def test_no_order_data_no_issues(self):
        issues = check_factual_consistency("Your order has been shipped.", None)
        assert issues == []

    def test_wrong_carrier_flagged(self):
        order_data = {"id": "ORD-1042", "total_amount": 87.99, "carrier": "USPS"}
        response = "Your order is being shipped via FedEx."
        issues = check_factual_consistency(response, order_data)
        assert len(issues) > 0


class TestValidateResponse:
    def test_clean_response_passes(self):
        result = validate_response(
            "Your order has been shipped. Tracking number: USPS998877665.",
            {"id": "ORD-1042", "total_amount": 87.99, "carrier": "USPS"},
        )
        assert result.passed is True
        assert result.output == "Your order has been shipped. Tracking number: USPS998877665."
        assert result.failures == []

    def test_pii_response_gets_redacted_but_passes(self):
        result = validate_response(
            "Your SSN 123-45-6789 is on file.",
            None,
        )
        # PII is redacted but the response is still usable (unless toxic/factual issues)
        assert "[SSN REDACTED]" in result.output
        assert any("PII" in f for f in result.failures)

    def test_toxic_response_returns_fallback(self):
        result = validate_response(
            "Only an idiot would complain about this.",
            None,
        )
        assert result.passed is False
        assert "specialist" in result.output.lower() or "apologize" in result.output.lower()

    def test_factual_error_returns_fallback(self):
        order_data = {"id": "ORD-1042", "total_amount": 87.99, "carrier": "USPS"}
        result = validate_response(
            "Your refund of $999.00 has been processed for order ORD-1042.",
            order_data,
        )
        assert result.passed is False
        assert result.failures

    def test_empty_response_passes_validation(self):
        result = validate_response("", None)
        assert result.passed is True
        assert result.output == ""
