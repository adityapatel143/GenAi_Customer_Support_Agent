"""Pytest configuration: disable all external service connections during tests.

Unsets LangSmith / LangChain tracing env vars so no network calls are made to
smith.langchain.com during the test run. Also patches load_dotenv so the .env
file cannot re-inject those vars after the unset.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Variables that trigger LangSmith auto-tracing or client init
_LANGSMITH_VARS = [
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_PROJECT",
    "LANGCHAIN_ENDPOINT",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_ENDPOINT",
]


def pytest_configure(config: pytest.Config) -> None:
    """Strip LangSmith env vars as early as possible — before any module import."""
    for var in _LANGSMITH_VARS:
        os.environ.pop(var, None)


@pytest.fixture(autouse=True)
def _disable_external_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-test fixture: keep LangSmith vars cleared and prevent load_dotenv
    from re-loading them from the .env file during the test."""
    for var in _LANGSMITH_VARS:
        monkeypatch.delenv(var, raising=False)

    # Prevent load_dotenv (called at config.py import time) from re-injecting vars
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: False)
