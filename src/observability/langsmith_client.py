import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_langsmith_client: Any = None


def _is_configured() -> bool:
    from src.config import get_settings
    s = get_settings()
    if not s.observability_enabled:
        return False
    return bool(s.langsmith_api_key and not s.langsmith_api_key.startswith("ls__..."))


def get_langsmith_client() -> Any:
    """Return a singleton LangSmith Client, or None if not configured."""
    global _langsmith_client
    if _langsmith_client is not None:
        return _langsmith_client

    if not _is_configured():
        logger.warning("LangSmith API key not configured — observability disabled.")
        return None

    try:
        from langsmith import Client
        from src.config import get_settings
        s = get_settings()
        _langsmith_client = Client(
            api_url=s.langsmith_endpoint,
            api_key=s.langsmith_api_key,
        )
        logger.info("LangSmith client initialized (project: %s)", s.langsmith_project)
    except Exception as exc:
        logger.warning("LangSmith client initialization failed: %s", exc)
        _langsmith_client = None

    return _langsmith_client


def get_langfuse_callback_handler() -> None:
    """No-op: LangSmith auto-traces LangGraph via LANGCHAIN_TRACING_V2 env var.

    Set LANGCHAIN_TRACING_V2=true, LANGCHAIN_API_KEY, and LANGCHAIN_PROJECT in .env
    for automatic LangGraph tracing without an explicit callback handler.
    """
    return None


def create_trace(
    session_name: str,
    customer_id: str | None,
    ticket_id: str | None,
    intent: str | None,
) -> dict[str, Any] | None:
    """Create a LangSmith run (trace) for a support session.

    Returns a dict with 'client', 'run_id', and 'project' for use in log_event/log_score.
    """
    client = get_langsmith_client()
    if client is None:
        return None

    try:
        from src.config import get_settings
        s = get_settings()
        run_id = uuid.uuid4()
        client.create_run(
            id=run_id,
            name=session_name,
            run_type="chain",
            project_name=s.langsmith_project,
            inputs={
                "customer_id": customer_id,
                "ticket_id": ticket_id,
                "intent": intent,
                "session_start_time": datetime.now(tz=timezone.utc).isoformat(),
            },
        )
        return {"client": client, "run_id": run_id, "project": s.langsmith_project}
    except Exception as exc:
        logger.warning("Failed to create LangSmith run: %s", exc)
        return None


def log_event(
    trace: dict[str, Any] | None,
    event_name: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log a custom event as a child run on an existing LangSmith trace."""
    if trace is None:
        return
    try:
        client: Any = trace["client"]
        child_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc)
        client.create_run(
            id=child_id,
            name=event_name,
            run_type="tool",
            project_name=trace["project"],
            parent_run_id=trace["run_id"],
            inputs=metadata or {},
            start_time=now,
        )
        client.update_run(child_id, outputs={"status": "logged"}, end_time=now)
        # If this is the final event, close the root run too
        if event_name == "session_completed":
            client.update_run(
                trace["run_id"],
                outputs=metadata or {},
                end_time=datetime.now(tz=timezone.utc),
            )
    except Exception as exc:
        logger.warning("Failed to log LangSmith event '%s': %s", event_name, exc)


def log_score(
    trace: dict[str, Any] | None,
    name: str,
    value: float,
    comment: str | None = None,
) -> None:
    """Log a numeric score (feedback) to an existing LangSmith trace."""
    if trace is None:
        return
    try:
        client: Any = trace["client"]
        client.create_feedback(
            run_id=trace["run_id"],
            key=name,
            score=value,
            comment=comment,
        )
    except Exception as exc:
        logger.warning("Failed to log LangSmith score '%s': %s", name, exc)


def get_trace_url(trace: dict[str, Any] | None) -> str | None:
    """Return the LangSmith UI URL for the given trace run."""
    if trace is None:
        return None
    try:
        from src.config import get_settings
        s = get_settings()
        project = trace.get("project", s.langsmith_project)
        run_id = trace.get("run_id")
        return f"https://smith.langchain.com/projects/{project}/runs/{run_id}"
    except Exception:
        return None
