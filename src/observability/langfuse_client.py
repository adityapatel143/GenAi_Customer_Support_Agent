"""Backward-compatibility shim: re-exports everything from langsmith_client.

Langfuse was replaced by LangSmith. All callers that imported from this module
continue to work unchanged.
"""
from src.observability.langsmith_client import (  # noqa: F401
    create_trace,
    get_langfuse_callback_handler,
    get_langsmith_client as get_langfuse_client,
    get_trace_url,
    log_event,
    log_score,
)
