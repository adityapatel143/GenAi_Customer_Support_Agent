import logging
import os
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env into os.environ so LangSmith picks up LANGCHAIN_TRACING_V2,
# LANGCHAIN_API_KEY, LANGCHAIN_PROJECT etc. before anything else runs.
load_dotenv(override=False)

# Role literals used by get_llm() — one per node that calls an LLM.
LLMRole = Literal["router", "wismo", "returns", "refunds", "responder", "escalation", "off_topic", "cancellations"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI — shared fallback (used when a role-specific key is not set)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.1
    openai_max_tokens: int = 1024

    # Per-role model overrides
    # Each role falls back to openai_model / openai_temperature / openai_max_tokens if not set.
    # router  — fast, cheap; classifies intent from a short message
    router_model: str = "gpt-4o-mini"
    router_temperature: float = 0.0
    router_max_tokens: int = 256
    # wismo — must reliably call tools and parse structured data
    wismo_model: str = "gpt-4o"
    wismo_temperature: float = 0.0
    wismo_max_tokens: int = 1024
    # returns — must reason about eligibility rules and call tools correctly
    returns_model: str = "gpt-4o"
    returns_temperature: float = 0.0
    returns_max_tokens: int = 1024
    # refunds — same as returns
    refunds_model: str = "gpt-4o"
    refunds_temperature: float = 0.0
    refunds_max_tokens: int = 1024
    # responder — highest-quality output; composing the final customer-facing reply
    responder_model: str = "gpt-4o"
    responder_temperature: float = 0.2
    responder_max_tokens: int = 1024
    # escalation — empathetic, context-aware handoff message when routing to a human agent
    escalation_model: str = "gpt-4o-mini"
    escalation_temperature: float = 0.3
    escalation_max_tokens: int = 512
    # off_topic — natural, contextual refusal for out-of-scope or harmful requests
    off_topic_model: str = "gpt-4o-mini"
    off_topic_temperature: float = 0.3
    off_topic_max_tokens: int = 256
    # cancellations — handles order cancellation requests
    cancellations_model: str = "gpt-4o-mini"
    cancellations_temperature: float = 0.2
    cancellations_max_tokens: int = 512

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # LangSmith / Observability
    # Set OBSERVABILITY_ENABLED=false in .env to fully disable all tracing and logging.
    observability_enabled: bool = True
    langsmith_api_key: str = ""
    langsmith_project: str = "customer-support-agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # Business Rules
    return_window_days: int = 30
    escalation_refund_threshold: float = 500.0
    max_auto_retries: int = 3
    fraud_score_threshold: float = 0.7

    # Ollama (local inference)
    # Set USE_OLLAMA=true to route ALL LLM calls to a local Ollama server instead of OpenAI.
    # Set OLLAMA_BASE_URL if Ollama is not on the default localhost:11434.
    # Each {ROLE}_MODEL still controls which Ollama model is used per node
    # (e.g. WISMO_MODEL=llama3.2). OpenAI model names are ignored when use_ollama=True.
    use_ollama: bool = False
    ollama_base_url: str = "http://localhost:11434"

    # App
    app_title: str = "Customer Support Agent"
    app_debug: bool = False
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    # If observability is disabled, strip LangChain auto-tracing env vars so
    # LangGraph never attempts to connect to smith.langchain.com.
    if not s.observability_enabled:
        for var in (
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
        ):
            os.environ.pop(var, None)
    return s


def get_llm(role: LLMRole):
    """Return an LLM instance configured for the given node role.

    When USE_OLLAMA=true in .env, returns a ChatOllama instance pointed at
    OLLAMA_BASE_URL (default: http://localhost:11434).  The per-role
    {ROLE}_MODEL variable controls which Ollama model is loaded
    (e.g. WISMO_MODEL=llama3.2).  OpenAI is not contacted at all.

    When USE_OLLAMA=false (default), returns a ChatOpenAI instance.
    All roles share OPENAI_API_KEY; each role can override model /
    temperature / max_tokens via {ROLE}_MODEL, {ROLE}_TEMPERATURE,
    {ROLE}_MAX_TOKENS in .env.

    Role       Default (OpenAI)   Purpose
    ---------  ----------------   ------------------------------------------
    router     gpt-4o-mini        fast intent classification (low cost)
    wismo      gpt-4o             reliable tool calling + structured data
    returns    gpt-4o             eligibility reasoning + tool calling
    refunds    gpt-4o             refund-state reasoning + tool calling
    responder  gpt-4o             highest-quality customer-facing generation
    escalation gpt-4o-mini        empathetic human-handoff message
    off_topic  gpt-4o-mini        contextual out-of-scope refusal
    """
    s = get_settings()
    model       = getattr(s, f"{role}_model")
    temperature = getattr(s, f"{role}_temperature")
    max_tokens  = getattr(s, f"{role}_max_tokens")

    if s.use_ollama:
        from langchain_ollama import ChatOllama  # local import — optional dep
        return ChatOllama(
            model=model,
            base_url=s.ollama_base_url,
            temperature=temperature,
            num_predict=max_tokens,
        )

    from langchain_openai import ChatOpenAI  # local import to avoid circular deps at module load
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        openai_api_key=s.openai_api_key,
    )


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
