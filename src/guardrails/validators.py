import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Patterns to detect and redact PII
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_PATTERN = re.compile(r"\b(?:\d[ -]?){13,16}\b")

# Simple toxic/profanity word list (extend as needed)
_TOXIC_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bstupid\b", r"\bidiot\b", r"\bmoron\b", r"\bdumb\b",
        r"\bbullshit\b", r"\bscam\b.*\bcompany\b", r"\bworthless\b",
    ]
]

# Prompt injection patterns — phrases that attempt to override system instructions
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore (all |previous |prior |your |the )?instructions",
        r"disregard (all |previous |prior |your )?instructions",
        r"forget (what you (were told|know)|your instructions|previous instructions)",
        r"new (system )?instructions?",
        r"override (your |the |all )?instructions",
        r"you are now",
        r"act as (if |though )?(you are|you were|a )?",
        r"pretend (you are|to be|that you)",
        r"(reveal|show|print|output|display) (your |the )?(system |hidden |original )?prompt",
        r"(reveal|expose|leak|dump) (all |customer |user )?data",
        r"jailbreak",
        r"\bDAN\b",  # Do Anything Now
        r"sudo (mode|override)",
        r"developer mode",
        r"(translate|repeat|echo) (everything|all|the above)",
    ]
]

# Allowed intent values the router is permitted to produce
ALLOWED_INTENTS = frozenset({"wismo", "return", "refund", "cancel", "escalate", "off_topic", "harmful", "other"})

_SAFE_FALLBACK = (
    "I apologize for any inconvenience. A support specialist will review your request "
    "and respond shortly. Your ticket has been flagged for immediate attention."
)


class ValidationResult:
    def __init__(self, passed: bool, output: str, failures: list[str]) -> None:
        self.passed = passed
        self.output = output
        self.failures = failures


def check_prompt_injection(text: str) -> list[str]:
    """Detect prompt injection attempts in user input.

    Returns a list of matched injection patterns if found.
    """
    found = []
    for pat in _INJECTION_PATTERNS:
        match = pat.search(text)
        if match:
            found.append(match.group(0))
    return found


class InputValidationResult:
    def __init__(self, safe: bool, reason: str | None = None) -> None:
        self.safe = safe
        self.reason = reason


def validate_input(text: str, max_length: int = 1000) -> InputValidationResult:
    """Validate user input before it reaches any LLM.

    Checks:
    1. Message length — reject inputs over max_length characters.
    2. Prompt injection — detect attempts to override system instructions.

    Returns InputValidationResult with safe=False and a reason if blocked.
    """
    if len(text) > max_length:
        logger.warning("Input rejected: length %d exceeds limit %d", len(text), max_length)
        return InputValidationResult(
            safe=False,
            reason=f"Message too long ({len(text)} chars). Please keep your message under {max_length} characters.",
        )

    injection_matches = check_prompt_injection(text)
    if injection_matches:
        logger.warning("Prompt injection attempt detected: %s", injection_matches)
        return InputValidationResult(
            safe=False,
            reason="I'm only able to assist with order tracking, returns, and refunds. How can I help you with your order?",
        )

    return InputValidationResult(safe=True)


def redact_pii(text: str) -> str:
    """Redact SSNs and credit card numbers from text."""
    text = _SSN_PATTERN.sub("[SSN REDACTED]", text)
    text = _CC_PATTERN.sub("[CARD REDACTED]", text)
    return text


def check_toxic_language(text: str) -> list[str]:
    """Return a list of toxic pattern matches found in text."""
    found = []
    for pat in _TOXIC_PATTERNS:
        match = pat.search(text)
        if match:
            found.append(match.group(0))
    return found


def check_factual_consistency(response: str, order_data: dict[str, Any] | None) -> list[str]:
    """Check that order facts mentioned in the response match order_data.

    Verifies: order ID, total_amount, carrier, tracking_number.
    Returns a list of inconsistency descriptions if any found.
    """
    if not order_data:
        return []

    inconsistencies: list[str] = []

    # Check total amount if mentioned
    amount = order_data.get("total_amount")
    if amount is not None:
        amounts_in_response = re.findall(r"\$[\d,]+\.?\d*", response)
        for amt_str in amounts_in_response:
            val = float(amt_str.replace("$", "").replace(",", ""))
            if abs(val - amount) > 0.01 and val > 0:
                inconsistencies.append(
                    f"Response mentions ${val:.2f} but order total is ${amount:.2f}"
                )

    # Check order ID if mentioned
    order_id = order_data.get("id")
    if order_id:
        ids_in_response = re.findall(r"ORD-\d+", response)
        for mentioned_id in ids_in_response:
            if mentioned_id != order_id:
                inconsistencies.append(
                    f"Response mentions order {mentioned_id} but context is for {order_id}"
                )

    # Check carrier — only flag if the response names a DIFFERENT carrier while
    # also stating the actual carrier is wrong (not just mentioning it in passing).
    carrier = order_data.get("carrier")
    if carrier:
        known_carriers = ["FedEx", "UPS", "USPS", "DHL"]
        for c in known_carriers:
            if c.lower() != carrier.lower() and re.search(rf"\b{c}\b", response, re.IGNORECASE):
                # Only flag if the actual correct carrier is NOT also mentioned
                if not re.search(rf"\b{re.escape(carrier)}\b", response, re.IGNORECASE):
                    inconsistencies.append(
                        f"Response mentions carrier {c} but actual carrier is {carrier}"
                    )

    # Check tracking number — if order has one and response contains a different tracking-like string
    tracking = order_data.get("tracking_number")
    if tracking:
        # Look for tracking numbers: 8+ alphanumeric chars that look like a tracking number
        tracking_pattern = re.compile(r"\b([A-Z]{2,5}\d{8,}|\d{12,22})\b")
        found_trackings = tracking_pattern.findall(response)
        for t in found_trackings:
            if t != tracking:
                inconsistencies.append(
                    f"Response contains tracking number {t} but actual tracking is {tracking}"
                )

    return inconsistencies


def validate_response(
    response: str,
    order_data: dict[str, Any] | None = None,
) -> ValidationResult:
    """Run all guardrail validators on an LLM response.

    1. PII redaction (SSN, credit card numbers)
    2. Toxic language detection
    3. Factual consistency with order_data

    Returns a ValidationResult with the (possibly redacted) output and any failures.
    """
    failures: list[str] = []

    # 1. PII redaction
    cleaned = redact_pii(response)
    if cleaned != response:
        failures.append("PII detected and redacted from response.")
        logger.warning("PII redaction applied to LLM response.")

    # 2. Toxic language
    toxic_matches = check_toxic_language(cleaned)
    if toxic_matches:
        failures.append(f"Toxic language detected: {toxic_matches}")
        logger.warning("Toxic language found in LLM response: %s", toxic_matches)
        # Return safe fallback instead of toxic output
        return ValidationResult(passed=False, output=_SAFE_FALLBACK, failures=failures)

    # 3. Factual consistency — log inconsistencies but do NOT replace the response.
    # Replacing with a generic fallback on a false positive (e.g. multi-order history)
    # is worse than showing a slightly imperfect response; the LLM output stays.
    fact_issues = check_factual_consistency(cleaned, order_data)
    if fact_issues:
        for issue in fact_issues:
            failures.append(f"Factual inconsistency: {issue}")
            logger.warning("Factual inconsistency in LLM response: %s", issue)

    passed = len(failures) == 0
    return ValidationResult(passed=passed, output=cleaned, failures=failures)
